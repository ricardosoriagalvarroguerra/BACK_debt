"""Servicio de simulación de escenarios."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from sqlalchemy.orm import Session, joinedload
from dateutil.relativedelta import relativedelta

from app.models.scenario import Scenario, ScenarioAssumption, ScenarioResult
from app.models.balance import Balance
from app.models.disbursement import Disbursement
from app.models.contract import Contract
from app.models.config import SystemConfig


class ScenarioService:
    """Servicio para gestionar y ejecutar escenarios."""

    @staticmethod
    def create_scenario(
        db: Session,
        name: str,
        description: Optional[str],
        is_base: bool,
        created_by: int,
    ) -> Scenario:
        """Crea un nuevo escenario."""
        scenario = Scenario(
            name=name,
            description=description,
            is_base=is_base,
            status="BORRADOR",
            created_by=created_by,
        )
        db.add(scenario)
        db.commit()
        db.refresh(scenario)
        return scenario

    @staticmethod
    def add_assumption(
        db: Session,
        scenario_id: int,
        assumption_data: dict,
    ) -> ScenarioAssumption:
        """Añade una assumption a un escenario."""
        assumption = ScenarioAssumption(
            scenario_id=scenario_id,
            **assumption_data,
        )
        db.add(assumption)
        db.commit()
        db.refresh(assumption)
        return assumption

    @staticmethod
    def _calculate_hypothetical_outstanding(
        assumption: ScenarioAssumption,
        current_date: date,
    ) -> Decimal:
        """
        Calcula el saldo vigente de un nuevo desembolso hipotético en una fecha dada,
        respetando fechas de inicio/fin y tipo de amortización.
        """
        amount = assumption.hypothetical_amount_usd or Decimal(0)
        if amount <= 0:
            return Decimal(0)

        start = assumption.hypothetical_start_date
        end = assumption.hypothetical_end_date

        # Si no hay fechas, comportamiento legacy: monto constante siempre
        if not start and not end:
            return amount

        # Antes del inicio: no hay saldo
        if start and current_date < start:
            return Decimal(0)

        # Después del vencimiento: saldo 0
        if end and current_date > end:
            return Decimal(0)

        amort_type = (assumption.hypothetical_amort_type or "BULLET").upper()

        if amort_type == "BULLET":
            # Saldo constante hasta vencimiento
            return amount

        elif amort_type == "AMORTIZABLE":
            if not start or not end:
                return amount
            # Amortización lineal mensual
            total_months = (end.year - start.year) * 12 + (end.month - start.month)
            if total_months <= 0:
                return Decimal(0)
            elapsed_months = (current_date.year - start.year) * 12 + (current_date.month - start.month)
            remaining = max(Decimal(0), amount - (amount * Decimal(elapsed_months) / Decimal(total_months)))
            return remaining

        # Default: bullet
        return amount

    @staticmethod
    def run_simulation(
        db: Session,
        scenario_id: int,
        from_date: date,
        to_date: date,
    ) -> List[ScenarioResult]:
        """
        Ejecuta la simulación de un escenario.

        Toma la proyección base del portafolio y superpone los shocks
        y nuevos desembolsos definidos en las assumptions.
        """
        scenario = (
            db.query(Scenario)
            .options(joinedload(Scenario.assumptions))
            .filter(Scenario.id == scenario_id)
            .first()
        )
        if not scenario:
            raise ValueError(f"Scenario {scenario_id} not found")

        # Eliminar resultados previos
        db.query(ScenarioResult).filter(
            ScenarioResult.scenario_id == scenario_id
        ).delete()
        db.commit()

        # Pre-fetch ceiling config ONCE before the loop
        ceiling_row = db.query(SystemConfig).filter(SystemConfig.key == "debt_ceiling_usd_mm").first()
        ceiling_value = Decimal(str(ceiling_row.value)) if ceiling_row else Decimal(2500)

        results = []
        current_date = from_date

        # Helper: advance to last day of the next month
        def next_month_end(d: date) -> date:
            """Return last day of the next month."""
            first_of_next = (d.replace(day=1) + relativedelta(months=2))
            return first_of_next - relativedelta(days=1)

        while current_date <= to_date:
            # Obtener saldos del portafolio con JOIN a disbursements (evita N+1)
            balances = (
                db.query(Balance)
                .join(Disbursement, Balance.disbursement_id == Disbursement.id)
                .filter(
                    Balance.period_date == current_date,
                    Disbursement.status == "DESEMBOLSADO",
                )
                .options(joinedload(Balance.disbursement))
                .all()
            )

            # Calcular agregados
            total_outstanding = Decimal(0)
            ifd_outstanding = Decimal(0)
            market_outstanding = Decimal(0)
            hypothetical_outstanding = Decimal(0)

            weighted_spread = Decimal(0)
            weighted_term = Decimal(0)
            total_weight = Decimal(0)

            total_debt_service = Decimal(0)
            total_principal = Decimal(0)
            total_interest = Decimal(0)

            for bal in balances:
                disb = bal.disbursement

                total_outstanding += bal.outstanding_usd

                # Categorizar por excel_sheet (case-insensitive)
                sheet = (disb.excel_sheet or "").upper()
                if sheet == "IFD":
                    ifd_outstanding += bal.outstanding_usd
                elif sheet == "MERCADO":
                    market_outstanding += bal.outstanding_usd

                # Ponderadores para promedios
                if bal.outstanding_usd > 0:
                    if bal.spread_bps:
                        weighted_spread += bal.spread_bps * bal.outstanding_usd
                    if bal.residual_term_years:
                        weighted_term += bal.residual_term_years * bal.outstanding_usd
                    total_weight += bal.outstanding_usd

                # Servicio de deuda
                total_debt_service += bal.debt_service_usd or Decimal(0)
                total_principal += bal.amortization_usd or Decimal(0)
                total_interest += bal.interest_usd or Decimal(0)

            # Calcular promedios ponderados
            avg_spread = (
                weighted_spread / total_weight
                if total_weight > 0
                else Decimal(0)
            )
            avg_term = (
                weighted_term / total_weight
                if total_weight > 0
                else Decimal(0)
            )

            # Aplicar shocks por assumptions
            for assumption in scenario.assumptions:
                if assumption.assumption_type == "RATE_SHOCK":
                    # Ajustar spread
                    shock = assumption.rate_shock_bps or Decimal(0)
                    avg_spread += shock

                elif assumption.assumption_type == "FX_SHOCK":
                    # Ajustar montos en FX
                    shock_pct = assumption.fx_shock_pct or Decimal(0)
                    adjustment = total_outstanding * (shock_pct / Decimal(100))
                    total_outstanding += adjustment

                elif assumption.assumption_type == "NUEVO_DESEMBOLSO":
                    # Calcular saldo hipotético con amortización y fechas
                    hyp_balance = ScenarioService._calculate_hypothetical_outstanding(
                        assumption, current_date
                    )
                    if hyp_balance > 0:
                        hypothetical_outstanding += hyp_balance
                        total_outstanding += hyp_balance
                        ifd_outstanding += hyp_balance  # Default: IFD (can be extended)

                        # Include hypothetical spread in weighted average
                        if assumption.hypothetical_spread_bps and hyp_balance > 0:
                            weighted_spread += assumption.hypothetical_spread_bps * hyp_balance
                            total_weight += hyp_balance
                            avg_spread = weighted_spread / total_weight if total_weight > 0 else Decimal(0)

                elif assumption.assumption_type == "PREPAGO":
                    # Reducir outstanding
                    reduction = assumption.hypothetical_amount_usd or Decimal(0)
                    total_outstanding = max(total_outstanding - reduction, Decimal(0))

            # Calculate ceiling utilization (ceiling_value fetched once before loop)
            ceiling_pct = (total_outstanding / ceiling_value) * Decimal(100)

            # Determinar status
            if ceiling_pct <= Decimal(80):
                ceiling_status = "VERDE"
            elif ceiling_pct <= Decimal(90):
                ceiling_status = "AMARILLO"
            elif ceiling_pct <= Decimal(100):
                ceiling_status = "NARANJA"
            else:
                ceiling_status = "ROJO"

            result = ScenarioResult(
                scenario_id=scenario_id,
                period_date=current_date,
                total_outstanding_usd=total_outstanding,
                ifd_outstanding_usd=ifd_outstanding,
                market_outstanding_usd=market_outstanding,
                hypothetical_usd=hypothetical_outstanding,
                weighted_avg_spread_bps=avg_spread,
                weighted_avg_term_years=avg_term,
                debt_service_usd=total_debt_service,
                principal_usd=total_principal,
                interest_usd=total_interest,
                ceiling_utilization_pct=ceiling_pct,
                ceiling_status=ceiling_status,
            )
            db.add(result)
            results.append(result)

            current_date = next_month_end(current_date)

        db.commit()
        return results

    @staticmethod
    def compare_scenarios(
        db: Session,
        scenario_ids: List[int],
        from_date: date,
        to_date: date,
    ) -> dict:
        """Compara múltiples escenarios."""
        comparison = {}

        for scenario_id in scenario_ids:
            scenario = db.query(Scenario).get(scenario_id)
            if not scenario:
                continue

            results = (
                db.query(ScenarioResult)
                .filter(
                    ScenarioResult.scenario_id == scenario_id,
                    ScenarioResult.period_date >= from_date,
                    ScenarioResult.period_date <= to_date,
                )
                .order_by(ScenarioResult.period_date)
                .all()
            )

            comparison[scenario.name] = {
                "scenario_id": scenario_id,
                "results": results,
            }

        return comparison
