"""Service for Annual Debt Planning Wizard."""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import extract

from app.models.disbursement import Disbursement
from app.models.contract import Contract
from app.models.creditor import Creditor
from app.models.currency import Currency
from app.models.balance import Balance
from app.models.config import SystemConfig
from app.models.scenario import Scenario, ScenarioAssumption
from app.schemas.annual_planning import (
    MaturityItem, MaturityDecision, AdditionalOperation,
    KPISnapshot, TimelinePoint, QuickSimulateRequest, QuickSimulateResponse,
)


class AnnualPlanningService:

    @staticmethod
    def get_maturities_for_year(db: Session, year: int) -> List[MaturityItem]:
        """Get all instruments maturing in the given year."""
        rows = (
            db.query(Disbursement, Contract, Creditor, Currency)
            .join(Contract, Disbursement.contract_id == Contract.id)
            .join(Creditor, Contract.creditor_id == Creditor.id)
            .join(Currency, Contract.currency_id == Currency.id)
            .filter(
                extract("year", Disbursement.maturity_date) == year,
                Disbursement.status == "DESEMBOLSADO",
            )
            .order_by(Disbursement.maturity_date)
            .all()
        )

        return [
            MaturityItem(
                disbursement_id=d.id,
                disbursement_code=d.disbursement_code,
                disbursement_name=d.disbursement_name,
                creditor_code=cr.code,
                creditor_name=cr.name,
                creditor_type=cr.creditor_type,
                contract_code=c.contract_code,
                amount_usd=float(d.amount_usd),
                maturity_date=d.maturity_date,
                spread_bps=float(d.effective_spread_bps) if d.effective_spread_bps else (
                    float(c.spread_bps) if c.spread_bps else None
                ),
                currency_code=cur.code,
                amortization_type=c.amortization_type or "BULLET",
            )
            for d, c, cr, cur in rows
        ]

    @staticmethod
    def _get_current_kpis(db: Session) -> dict:
        """Calculate current portfolio KPIs from latest balances."""
        # Find the period_date with the most instrument coverage (closest to now)
        from sqlalchemy import func as sqlfunc
        latest_date = (
            db.query(Balance.period_date)
            .join(Disbursement, Balance.disbursement_id == Disbursement.id)
            .filter(
                Disbursement.status == "DESEMBOLSADO",
                Balance.period_date <= date.today() + relativedelta(months=6),
            )
            .group_by(Balance.period_date)
            .order_by(sqlfunc.count().desc(), Balance.period_date.desc())
            .first()
        )
        if not latest_date:
            return {
                "outstanding": 0, "ceiling_pct": 0, "spread_pp": 0,
                "term_pp": 0, "debt_service": 0, "period_date": date.today(),
            }

        period = latest_date[0]

        balances = (
            db.query(Balance)
            .join(Disbursement, Balance.disbursement_id == Disbursement.id)
            .filter(
                Balance.period_date == period,
                Disbursement.status == "DESEMBOLSADO",
            )
            .all()
        )

        total_outstanding = Decimal(0)
        weighted_spread = Decimal(0)
        weighted_term = Decimal(0)
        total_weight = Decimal(0)
        total_debt_service = Decimal(0)

        for b in balances:
            total_outstanding += b.outstanding_usd or Decimal(0)
            total_debt_service += b.debt_service_usd or Decimal(0)
            if b.outstanding_usd and b.outstanding_usd > 0:
                if b.spread_bps:
                    weighted_spread += b.spread_bps * b.outstanding_usd
                if b.residual_term_years:
                    weighted_term += b.residual_term_years * b.outstanding_usd
                total_weight += b.outstanding_usd

        spread_pp = float(weighted_spread / total_weight) if total_weight > 0 else 0
        term_pp = float(weighted_term / total_weight) if total_weight > 0 else 0

        ceiling_row = db.query(SystemConfig).filter(SystemConfig.key == "debt_ceiling_usd_mm").first()
        ceiling_limit = float(ceiling_row.value) if ceiling_row else 2500.0
        ceiling_pct = (float(total_outstanding) / ceiling_limit * 100) if ceiling_limit > 0 else 0

        return {
            "outstanding": float(total_outstanding),
            "ceiling_pct": ceiling_pct,
            "spread_pp": spread_pp,
            "term_pp": term_pp,
            "debt_service": float(total_debt_service) * 12,  # annualized
            "ceiling_limit": ceiling_limit,
            "period_date": period,
        }

    @staticmethod
    def quick_simulate(db: Session, request: QuickSimulateRequest) -> QuickSimulateResponse:
        """Run a quick in-memory simulation without persisting results."""
        current = AnnualPlanningService._get_current_kpis(db)

        # Start from current state
        proj_outstanding = current["outstanding"]
        proj_spread_weighted = current["spread_pp"] * proj_outstanding
        proj_term_weighted = current["term_pp"] * proj_outstanding
        proj_weight = proj_outstanding
        ceiling_limit = current["ceiling_limit"]
        proj_debt_service_annual = current["debt_service"]

        # Build events from decisions
        events = []  # (date, delta_outstanding, delta_spread_contribution, delta_term_contribution, description)

        for dec in request.decisions:
            if dec.action == "VENCER":
                # Find the maturity from DB
                disb = db.query(Disbursement).filter(Disbursement.id == dec.disbursement_id).first()
                if disb:
                    amt = float(disb.amount_usd)
                    spread = float(disb.effective_spread_bps or disb.contract.spread_bps or 0)
                    events.append({
                        "date": disb.maturity_date,
                        "delta": -amt,
                        "spread_remove": spread * amt,
                        "term_remove": 0,
                        "desc": f"Vencimiento {disb.disbursement_code}",
                    })

            elif dec.action == "REFINANCIAR":
                disb = db.query(Disbursement).filter(Disbursement.id == dec.disbursement_id).first()
                if disb:
                    old_amt = float(disb.amount_usd)
                    old_spread = float(disb.effective_spread_bps or disb.contract.spread_bps or 0)
                    new_amt = dec.new_amount or old_amt
                    new_spread = dec.new_spread_bps or old_spread
                    new_mat = dec.new_maturity_date or (disb.maturity_date + relativedelta(years=5))
                    new_term = (new_mat - disb.maturity_date).days / 365.25

                    # Remove old at maturity
                    events.append({
                        "date": disb.maturity_date,
                        "delta": -old_amt,
                        "spread_remove": old_spread * old_amt,
                        "term_remove": 0,
                        "desc": f"Vence {disb.disbursement_code}",
                    })
                    # Add new at same date
                    events.append({
                        "date": disb.maturity_date,
                        "delta": new_amt,
                        "spread_add": new_spread * new_amt,
                        "term_add": new_term * new_amt,
                        "desc": dec.new_description or f"Refinancia {disb.disbursement_code}",
                    })

        for op in request.additional_operations:
            start = op.start_date or date(request.year, 1, 1)
            term_years = (op.maturity_date - start).days / 365.25
            events.append({
                "date": start,
                "delta": op.amount_usd,
                "spread_add": op.spread_bps * op.amount_usd,
                "term_add": term_years * op.amount_usd,
                "desc": op.description,
            })

        # Sort events by date
        events.sort(key=lambda e: e["date"])

        # Project quarterly timeline (from start of year to +3 years)
        timeline = []
        sim_outstanding = proj_outstanding
        sim_spread_w = proj_spread_weighted
        sim_term_w = proj_term_weighted
        sim_weight = proj_weight

        start_date = date(request.year, 1, 1)
        end_date = date(request.year + 3, 12, 31)
        current_date = start_date

        event_idx = 0
        final_outstanding = sim_outstanding
        final_spread_w = sim_spread_w
        final_term_w = sim_term_w
        final_weight = sim_weight

        while current_date <= end_date:
            # Apply all events up to this date
            while event_idx < len(events) and events[event_idx]["date"] <= current_date:
                ev = events[event_idx]
                sim_outstanding += ev["delta"]
                if "spread_remove" in ev:
                    sim_spread_w -= ev["spread_remove"]
                    sim_weight -= abs(ev["delta"])
                if "spread_add" in ev:
                    sim_spread_w += ev["spread_add"]
                    sim_weight += ev["delta"]
                if "term_add" in ev:
                    sim_term_w += ev["term_add"]
                event_idx += 1

            sim_outstanding = max(sim_outstanding, 0)
            ceiling_pct = (sim_outstanding / ceiling_limit * 100) if ceiling_limit > 0 else 0

            timeline.append(TimelinePoint(
                period_date=current_date.isoformat(),
                outstanding_usd=round(sim_outstanding, 2),
                ceiling_pct=round(ceiling_pct, 2),
            ))

            final_outstanding = sim_outstanding
            final_spread_w = sim_spread_w
            final_term_w = sim_term_w
            final_weight = sim_weight

            current_date += relativedelta(months=3)

        # Apply remaining events
        while event_idx < len(events):
            ev = events[event_idx]
            final_outstanding += ev["delta"]
            if "spread_remove" in ev:
                final_spread_w -= ev["spread_remove"]
                final_weight -= abs(ev["delta"])
            if "spread_add" in ev:
                final_spread_w += ev["spread_add"]
                final_weight += ev["delta"]
            if "term_add" in ev:
                final_term_w += ev["term_add"]
            event_idx += 1

        final_outstanding = max(final_outstanding, 0)
        proj_spread_pp = float(final_spread_w / final_weight) if final_weight > 0 else 0
        proj_term_pp = float(final_term_w / final_weight) if final_weight > 0 else 0
        proj_ceiling_pct = (final_outstanding / ceiling_limit * 100) if ceiling_limit > 0 else 0

        # Estimate annual debt service change
        net_delta = final_outstanding - current["outstanding"]
        avg_spread = proj_spread_pp if proj_spread_pp > 0 else current["spread_pp"]
        ds_delta = net_delta * avg_spread / 10000  # annual interest on net new debt
        proj_ds = current["debt_service"] + ds_delta

        kpi = KPISnapshot(
            current_outstanding_usd=round(current["outstanding"], 2),
            projected_outstanding_usd=round(final_outstanding, 2),
            current_ceiling_pct=round(current["ceiling_pct"], 2),
            projected_ceiling_pct=round(proj_ceiling_pct, 2),
            current_spread_pp=round(current["spread_pp"], 2),
            projected_spread_pp=round(proj_spread_pp, 2),
            current_term_pp=round(current["term_pp"], 2),
            projected_term_pp=round(proj_term_pp, 2),
            current_debt_service=round(current["debt_service"], 2),
            projected_debt_service=round(proj_ds, 2),
            ceiling_limit_usd=ceiling_limit,
        )

        return QuickSimulateResponse(kpi=kpi, timeline=timeline)

    @staticmethod
    def save_as_scenario(
        db: Session,
        request,  # SavePlanRequest
        user_id: int,
    ) -> int:
        """Save the annual plan as a Scenario with assumptions."""
        name = request.name or f"Plan {request.year}"
        desc = request.description or f"Planificacion anual de endeudamiento {request.year}"

        scenario = Scenario(
            name=name,
            description=desc,
            status="BORRADOR",
            is_base=False,
            created_by=user_id,
        )
        db.add(scenario)
        db.flush()

        order = 1

        # Convert decisions to assumptions
        for dec in request.decisions:
            if dec.action == "OMITIR":
                continue

            disb = db.query(Disbursement).filter(Disbursement.id == dec.disbursement_id).first()
            if not disb:
                continue

            if dec.action == "VENCER":
                assumption = ScenarioAssumption(
                    scenario_id=scenario.id,
                    assumption_order=order,
                    assumption_type="PREPAGO",
                    description=f"Vencimiento {disb.disbursement_code} ({disb.disbursement_name})",
                    hypothetical_amount_usd=Decimal(str(disb.amount_usd)),
                    hypothetical_start_date=disb.maturity_date,
                )
                db.add(assumption)
                order += 1

            elif dec.action == "REFINANCIAR":
                # Prepago del original
                assumption_prepago = ScenarioAssumption(
                    scenario_id=scenario.id,
                    assumption_order=order,
                    assumption_type="PREPAGO",
                    description=f"Vence {disb.disbursement_code}",
                    hypothetical_amount_usd=Decimal(str(disb.amount_usd)),
                    hypothetical_start_date=disb.maturity_date,
                )
                db.add(assumption_prepago)
                order += 1

                # Nuevo desembolso
                new_amt = dec.new_amount or float(disb.amount_usd)
                new_spread = dec.new_spread_bps or float(disb.effective_spread_bps or disb.contract.spread_bps or 0)
                new_mat = dec.new_maturity_date or (disb.maturity_date + relativedelta(years=5))

                assumption_new = ScenarioAssumption(
                    scenario_id=scenario.id,
                    assumption_order=order,
                    assumption_type="NUEVO_DESEMBOLSO",
                    description=dec.new_description or f"Refinanciamiento {disb.disbursement_code}",
                    hypothetical_amount_usd=Decimal(str(new_amt)),
                    hypothetical_spread_bps=Decimal(str(new_spread)),
                    hypothetical_start_date=disb.maturity_date,
                    hypothetical_end_date=new_mat,
                    parameters={"amort_type": dec.new_amort_type or "BULLET", "currency": dec.new_currency or "USD", "creditor_type": "MERCADO"},
                )
                db.add(assumption_new)
                order += 1

        # Convert additional operations to assumptions
        for op in request.additional_operations:
            assumption = ScenarioAssumption(
                scenario_id=scenario.id,
                assumption_order=order,
                assumption_type="NUEVO_DESEMBOLSO",
                description=op.description,
                hypothetical_amount_usd=Decimal(str(op.amount_usd)),
                hypothetical_spread_bps=Decimal(str(op.spread_bps)),
                hypothetical_start_date=op.start_date or date(request.year, 1, 1),
                hypothetical_end_date=op.maturity_date,
                parameters={"amort_type": op.amort_type, "currency": op.currency, "creditor_type": op.creditor_type},
            )
            db.add(assumption)
            order += 1

        db.commit()
        return scenario.id
