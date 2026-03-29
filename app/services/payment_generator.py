"""Generador de calendarios de pago."""
import calendar
from datetime import date
from dateutil.relativedelta import relativedelta
from decimal import Decimal
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models.disbursement import Disbursement
from app.models.contract import Contract
from app.models.payment import PaymentSchedule
from app.services.calculation_engine import CalculationEngine


def _end_of_month(d: date) -> date:
    """Return the last day of the month for the given date."""
    last_day = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=last_day)


class PaymentGenerator:
    """Genera calendarios de pago para desembolsos."""

    FREQUENCY_MONTHS = {
        "MENSUAL": 1,
        "TRIMESTRAL": 3,
        "SEMESTRAL": 6,
        "ANUAL": 12,
    }

    @staticmethod
    def generate_schedule(
        db: Session,
        disbursement_id: int,
        base_rate_bps: Decimal = Decimal("0"),
    ) -> List[PaymentSchedule]:
        """
        Genera el calendario completo de pagos para un desembolso.
        Incluye pagos de principal, interés y comisiones.
        """
        disbursement = db.query(Disbursement).get(disbursement_id)
        if not disbursement:
            raise ValueError(f"Desembolso {disbursement_id} no encontrado")

        contract = disbursement.contract
        if not contract:
            raise ValueError(f"Contrato no encontrado para desembolso {disbursement_id}")

        # Delete existing schedule
        db.query(PaymentSchedule).filter(
            PaymentSchedule.disbursement_id == disbursement_id
        ).delete()

        payments = []

        # Determine frequencies
        amort_freq = PaymentGenerator.FREQUENCY_MONTHS.get(
            contract.amort_frequency or "SEMESTRAL", 6
        )
        interest_freq = PaymentGenerator.FREQUENCY_MONTHS.get(
            contract.interest_frequency or "SEMESTRAL", 6
        )

        # Get spread
        spread_bps = disbursement.effective_spread_bps or contract.spread_bps or Decimal("0")

        # Calculate dates
        start = disbursement.disbursement_date
        end = disbursement.maturity_date
        # Use disbursement-level grace if available, otherwise contract-level
        grace_months = getattr(disbursement, 'grace_period_months', None)
        if grace_months is None:
            grace_months = contract.grace_period_months or 0
        grace_end = start + relativedelta(months=grace_months)

        # --- Step 1: Build principal amortization schedule (needed to compute declining balance) ---
        principal_payments = {}  # date -> amount mapping for balance reduction
        original_amount = Decimal(str(disbursement.amount_usd))

        if contract.amortization_type == "BULLET":
            # Single payment at maturity
            payment = PaymentSchedule(
                disbursement_id=disbursement_id,
                payment_type="PRINCIPAL",
                payment_date=end,
                amount_original=original_amount,
                amount_usd=original_amount,
                status="PROGRAMADO",
            )
            payments.append(payment)
            principal_payments[end] = original_amount

        elif contract.amortization_type in ("AMORTIZABLE",):
            # First amortization: after grace period, using end-of-month dates
            # If grace = 0: first payment at start + amort_freq (end of month)
            # If grace > 0: first payment at start + grace_months (end of month)
            if grace_months > 0:
                amort_start_raw = start + relativedelta(months=grace_months)
            else:
                amort_start_raw = start + relativedelta(months=amort_freq)
            amort_start = _end_of_month(amort_start_raw)

            # Collect all amortization dates (end-of-month), including maturity if needed
            amort_dates = []
            current = amort_start
            while current <= end:
                amort_dates.append(current)
                current_raw = amort_start_raw + relativedelta(months=amort_freq * len(amort_dates))
                current = _end_of_month(current_raw)

            # If the last amort date doesn't match maturity, add maturity as final payment
            if amort_dates and amort_dates[-1] < end:
                amort_dates.append(end)

            amort_periods = len(amort_dates)
            if amort_periods == 0:
                amort_periods = 1
                amort_dates = [end]

            payment_amount = original_amount / Decimal(str(amort_periods))

            for pay_date in amort_dates:
                payment = PaymentSchedule(
                    disbursement_id=disbursement_id,
                    payment_type="PRINCIPAL",
                    payment_date=pay_date,
                    amount_original=payment_amount,
                    amount_usd=payment_amount,
                    status="PROGRAMADO",
                )
                payments.append(payment)
                principal_payments[pay_date] = payment_amount

        elif contract.amortization_type == "REVOLVING":
            # REVOLVING: interest-only during life, principal at maturity (like BULLET)
            payment = PaymentSchedule(
                disbursement_id=disbursement_id,
                payment_type="PRINCIPAL",
                payment_date=end,
                amount_original=original_amount,
                amount_usd=original_amount,
                status="PROGRAMADO",
            )
            payments.append(payment)
            principal_payments[end] = original_amount

        # --- Step 2: Generate INTEREST payments on declining balance ---
        # Build a sorted list of all principal payment dates for balance tracking
        sorted_amort_dates = sorted(principal_payments.keys())

        # Interest dates also use end-of-month
        int_start_raw = start + relativedelta(months=interest_freq)
        current = _end_of_month(int_start_raw)
        outstanding = original_amount
        int_period_num = 1

        while current <= end:
            # Calculate days in this period
            prev_raw = start + relativedelta(months=interest_freq * (int_period_num - 1))
            prev = _end_of_month(prev_raw) if int_period_num > 1 else start
            days = (current - prev).days

            # Interest is calculated on the balance at the START of the period
            balance_for_interest = outstanding
            amort_in_period = Decimal("0")
            for amort_date in sorted_amort_dates:
                if amort_date <= prev:
                    pass  # Already reflected in outstanding
                elif amort_date <= current:
                    amort_in_period += principal_payments[amort_date]

            interest = CalculationEngine.interest_calculation(
                balance_for_interest, spread_bps, base_rate_bps, days
            )

            payment = PaymentSchedule(
                disbursement_id=disbursement_id,
                payment_type="INTEREST",
                payment_date=current,
                amount_original=interest,
                amount_usd=interest,
                status="PROGRAMADO",
            )
            payments.append(payment)

            # After this interest period, reduce outstanding for amortizations that occurred
            outstanding -= amort_in_period
            if outstanding < 0:
                outstanding = Decimal("0")

            int_period_num += 1
            next_raw = start + relativedelta(months=interest_freq * int_period_num)
            current = _end_of_month(next_raw)
            # Don't generate interest past maturity
            if current > end:
                break

        # --- Generate COMMITMENT FEE payments (if applicable) ---
        if contract.commitment_fee_bps and contract.commitment_fee_bps > 0:
            undisbursed = Decimal(str(contract.approved_amount)) - Decimal(str(disbursement.amount_original))
            if undisbursed > 0:
                fee_annual = undisbursed * Decimal(str(contract.commitment_fee_bps)) / Decimal("10000")
                fee_period = fee_annual / Decimal("2")  # Semestral

                current = start + relativedelta(months=6)
                while current <= end and undisbursed > 0:
                    payment = PaymentSchedule(
                        disbursement_id=disbursement_id,
                        payment_type="COMMITMENT_FEE",
                        payment_date=current,
                        amount_original=fee_period,
                        amount_usd=fee_period,
                        status="PROGRAMADO",
                    )
                    payments.append(payment)
                    current += relativedelta(months=6)

        # Sort by date and save
        payments.sort(key=lambda p: (p.payment_date, p.payment_type))

        for p in payments:
            db.add(p)
        db.commit()

        return payments

