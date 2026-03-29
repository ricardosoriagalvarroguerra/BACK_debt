"""Projection engine para proyectar saldos hacia adelante."""
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import List, Optional
from sqlalchemy.orm import Session, joinedload
from dateutil.relativedelta import relativedelta

from app.models.disbursement import Disbursement
from app.models.balance import Balance
from app.models.contract import Contract


class ProjectionEngine:
    """Motor de proyecciones mensuales de saldos."""

    @staticmethod
    def project_disbursement(
        db: Session,
        disbursement: Disbursement,
        from_date: date,
        to_date: date,
        force_regenerate: bool = False,
    ) -> List[Balance]:
        """
        Proyecta los saldos de un desembolso mes a mes.

        Args:
            db: Session de BD
            disbursement: Desembolso a proyectar
            from_date: Fecha de inicio
            to_date: Fecha de fin
            force_regenerate: Si True, elimina proyecciones previas

        Returns:
            Lista de balances proyectados
        """
        # Si force_regenerate, eliminar proyecciones previas (commit happens at end)
        if force_regenerate:
            db.query(Balance).filter(
                Balance.disbursement_id == disbursement.id,
                Balance.is_projected == True,
                Balance.period_date >= from_date,
                Balance.period_date <= to_date,
            ).delete()
            db.flush()

        # Obtener último saldo conocido
        last_balance = (
            db.query(Balance)
            .filter(
                Balance.disbursement_id == disbursement.id,
                Balance.is_projected == False,
            )
            .order_by(Balance.period_date.desc())
            .first()
        )

        if not last_balance:
            # No hay datos históricos, no proyectar
            return []

        projected_balances = []
        current_date = last_balance.period_date + relativedelta(months=1)
        current_outstanding = last_balance.outstanding_usd
        current_outstanding_orig = last_balance.outstanding_original

        # Parámetros de proyección - usar amortization_type del contrato
        amort_type = disbursement.contract.amortization_type or "BULLET"
        spread = disbursement.effective_spread_bps or Decimal(0)
        maturity = disbursement.maturity_date

        while current_date <= to_date:
            # Calcular residual term en años
            days_remaining = (maturity - current_date).days
            residual_term = Decimal(days_remaining) / Decimal(365.25)

            # Amortización según tipo
            if amort_type == "BULLET":
                # BULLET: saldo constante hasta vencimiento, luego 0
                if current_date >= maturity:
                    amortization = current_outstanding
                    current_outstanding = Decimal(0)
                    current_outstanding_orig = Decimal(0)
                else:
                    amortization = Decimal(0)

            elif amort_type == "AMORTIZABLE":
                # AMORTIZABLE: reducción lineal mensual
                months_remaining = (
                    (maturity.year - current_date.year) * 12
                    + (maturity.month - current_date.month)
                )
                if months_remaining <= 0:
                    amortization = current_outstanding
                    current_outstanding = Decimal(0)
                    current_outstanding_orig = Decimal(0)
                else:
                    amortization = current_outstanding / Decimal(months_remaining + 1)
                    current_outstanding -= amortization
                    current_outstanding_orig -= amortization

            else:
                # Default: BULLET
                if current_date >= maturity:
                    amortization = current_outstanding
                    current_outstanding = Decimal(0)
                    current_outstanding_orig = Decimal(0)
                else:
                    amortization = Decimal(0)

            # Calculate monthly interest: outstanding * spread_bps / 10000 / 12
            outstanding_for_interest = max(current_outstanding + amortization, Decimal(0))  # pre-amortization balance
            monthly_interest = outstanding_for_interest * spread / Decimal("10000") / Decimal("12") if spread > 0 else Decimal(0)

            # Crear record de balance proyectado
            balance = Balance(
                disbursement_id=disbursement.id,
                period_date=current_date,
                outstanding_original=max(current_outstanding_orig, Decimal(0)),
                outstanding_usd=max(current_outstanding, Decimal(0)),
                exchange_rate_used=Decimal(1),  # USD base
                residual_term_years=max(residual_term, Decimal(0)),
                spread_bps=spread,
                amortization_usd=amortization,
                interest_usd=monthly_interest,
                debt_service_usd=amortization + monthly_interest,
                is_projected=True,
                is_active=True,
            )
            db.add(balance)
            projected_balances.append(balance)

            current_date += relativedelta(months=1)

        db.commit()
        return projected_balances

    @staticmethod
    def project_portfolio(
        db: Session,
        from_date: date,
        to_date: date,
        contract_ids: Optional[List[int]] = None,
    ) -> int:
        """
        Proyecta todos los desembolsos del portafolio.

        Args:
            db: Session de BD
            from_date: Fecha de inicio
            to_date: Fecha de fin
            contract_ids: IDs de contratos a proyectar (None = todos)

        Returns:
            Cantidad de balances creados
        """
        query = db.query(Disbursement).options(joinedload(Disbursement.contract))
        if contract_ids:
            query = query.filter(Disbursement.contract_id.in_(contract_ids))

        disbursements = query.filter(Disbursement.status == "DESEMBOLSADO").all()

        total_created = 0
        for disb in disbursements:
            balances = ProjectionEngine.project_disbursement(
                db, disb, from_date, to_date, force_regenerate=True
            )
            total_created += len(balances)

        return total_created
