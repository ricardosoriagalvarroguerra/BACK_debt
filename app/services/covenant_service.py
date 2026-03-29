"""Servicio para evaluación de covenants."""
from datetime import date
from decimal import Decimal
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc

from app.models.covenant import Covenant, CovenantTracking
from app.models.balance import Balance
from app.models.disbursement import Disbursement
from app.models.contract import Contract
from app.models.creditor import Creditor


class CovenantService:
    """Servicio para evaluar compliance de covenants."""

    TRAFFIC_LIGHT_COLORS = {
        "VERDE": "GREEN",
        "AMARILLO": "YELLOW",
        "NARANJA": "ORANGE",
        "ROJO": "RED",
        "GRIS": "GRAY",
    }

    @staticmethod
    def _resolve_period_date(db: Session, period_date: date) -> date:
        """Encuentra el period_date real más cercano (último día de mes <= fecha dada)."""
        actual = (
            db.query(sqlfunc.max(Balance.period_date))
            .filter(
                Balance.outstanding_usd > 0,
                Balance.period_date <= period_date,
            )
            .scalar()
        )
        if actual:
            return actual
        # Fallback: earliest available
        earliest = (
            db.query(sqlfunc.min(Balance.period_date))
            .filter(Balance.outstanding_usd > 0)
            .scalar()
        )
        return earliest or period_date

    @staticmethod
    def calculate_total_outstanding(db: Session, period_date: date) -> Decimal:
        """Calcula el saldo total outstanding en USD para una fecha."""
        resolved = CovenantService._resolve_period_date(db, period_date)
        result = (
            db.query(sqlfunc.sum(Balance.outstanding_usd))
            .filter(Balance.period_date == resolved, Balance.outstanding_usd > 0)
            .scalar()
        )
        return result or Decimal(0)

    @staticmethod
    def calculate_ifd_outstanding(db: Session, period_date: date) -> Decimal:
        """Calcula el saldo IFD en USD para una fecha."""
        resolved = CovenantService._resolve_period_date(db, period_date)
        result = (
            db.query(sqlfunc.sum(Balance.outstanding_usd))
            .join(Disbursement, Balance.disbursement_id == Disbursement.id)
            .filter(
                Balance.period_date == resolved,
                Balance.outstanding_usd > 0,
                Disbursement.excel_sheet == "IFD",
            )
            .scalar()
        )
        return result or Decimal(0)

    @staticmethod
    def calculate_max_creditor_concentration(db: Session, period_date: date) -> Decimal:
        """Calcula la concentración máxima por acreedor (%)."""
        resolved = CovenantService._resolve_period_date(db, period_date)

        total = (
            db.query(sqlfunc.sum(Balance.outstanding_usd))
            .filter(Balance.period_date == resolved, Balance.outstanding_usd > 0)
            .scalar()
        ) or Decimal(0)

        if total <= 0:
            return Decimal(0)

        # Outstanding by creditor
        creditor_totals = (
            db.query(
                Creditor.short_name,
                sqlfunc.sum(Balance.outstanding_usd).label("total"),
            )
            .join(Disbursement, Balance.disbursement_id == Disbursement.id)
            .join(Contract, Disbursement.contract_id == Contract.id)
            .join(Creditor, Contract.creditor_id == Creditor.id)
            .filter(Balance.period_date == resolved, Balance.outstanding_usd > 0)
            .group_by(Creditor.short_name)
            .all()
        )

        if not creditor_totals:
            return Decimal(0)

        max_pct = max(
            (ct.total / total * Decimal(100)) for ct in creditor_totals
        )
        return max_pct

    @staticmethod
    def calculate_weighted_avg_term(db: Session, period_date: date) -> Decimal:
        """Calcula el plazo promedio ponderado (años)."""
        resolved = CovenantService._resolve_period_date(db, period_date)

        balances = (
            db.query(Balance)
            .filter(
                Balance.period_date == resolved,
                Balance.outstanding_usd > 0,
                Balance.residual_term_years.isnot(None),
            )
            .all()
        )

        if not balances:
            return Decimal(0)

        total_weight = sum(bal.outstanding_usd for bal in balances)
        if total_weight <= 0:
            return Decimal(0)

        weighted_term = sum(
            (bal.residual_term_years or Decimal(0)) * bal.outstanding_usd
            for bal in balances
        )
        return weighted_term / total_weight

    @staticmethod
    def calculate_debt_service(db: Session, period_date: date) -> Decimal:
        """Calcula el servicio de deuda total."""
        resolved = CovenantService._resolve_period_date(db, period_date)
        result = (
            db.query(sqlfunc.sum(Balance.debt_service_usd))
            .filter(Balance.period_date == resolved)
            .scalar()
        )
        return result or Decimal(0)

    @staticmethod
    def evaluate_covenant(
        db: Session,
        covenant: Covenant,
        period_date: date,
    ) -> Tuple[Optional[Decimal], str]:
        """
        Evalúa un covenant para una fecha específica.

        Retorna: (valor_actual, status, traffic_light, utilization_pct)
        """
        covenant_type = covenant.covenant_type.upper()

        # Calcular valor actual según tipo
        if covenant_type in ("TOTAL_DEBT_CEILING", "TOPE_ENDEUDAMIENTO"):
            current_value = CovenantService.calculate_total_outstanding(db, period_date)
        elif covenant_type == "IFD_CEILING":
            current_value = CovenantService.calculate_ifd_outstanding(db, period_date)
        elif covenant_type == "CONCENTRACION_ACREEDOR":
            current_value = CovenantService.calculate_max_creditor_concentration(db, period_date)
        elif covenant_type in ("PLAZO_MINIMO", "MINIMUM_AVERAGE_TERM"):
            current_value = CovenantService.calculate_weighted_avg_term(db, period_date)
        elif covenant_type == "DEBT_SERVICE_RATIO":
            current_value = CovenantService.calculate_debt_service(db, period_date)
        elif covenant_type == "MAXIMUM_AVERAGE_TERM":
            current_value = CovenantService.calculate_weighted_avg_term(db, period_date)
        else:
            current_value = Decimal(0)

        limit = covenant.limit_value

        # --- Lógica especial para PLAZO_MINIMO (mínimo, no máximo) ---
        # El covenant dice "plazo no debe ser inferior a X años"
        # Si current >= limit → CUMPLIMIENTO; si current < limit → INCUMPLIMIENTO
        if covenant_type in ("PLAZO_MINIMO", "MINIMUM_AVERAGE_TERM"):
            if limit > 0:
                # Ratio inverso: mientras más alto, mejor
                utilization_pct = (current_value / limit * Decimal(100))
            else:
                utilization_pct = Decimal(0)

            if current_value >= limit:
                status = "CUMPLIMIENTO"
                traffic_light = "VERDE"
            elif current_value >= limit * Decimal("0.9"):
                status = "CUMPLIMIENTO"
                traffic_light = "AMARILLO"
            elif current_value >= limit * Decimal("0.8"):
                status = "CUMPLIMIENTO"
                traffic_light = "NARANJA"
            else:
                status = "INCUMPLIMIENTO"
                traffic_light = "ROJO"

            return current_value, status, traffic_light, utilization_pct

        # --- Lógica estándar (techo): current no debe superar limit ---
        utilization_pct = (current_value / limit * Decimal(100)) if limit > 0 else Decimal(0)

        if utilization_pct <= Decimal(100):
            status = "CUMPLIMIENTO"
            if current_value <= (covenant.green_max or limit * Decimal("0.7")):
                traffic_light = "VERDE"
            elif current_value <= (covenant.yellow_max or limit * Decimal("0.85")):
                traffic_light = "AMARILLO"
            elif current_value <= (covenant.orange_max or limit):
                traffic_light = "NARANJA"
            else:
                traffic_light = "ROJO"
        else:
            status = "INCUMPLIMIENTO"
            traffic_light = "ROJO"

        return current_value, status, traffic_light, utilization_pct

    @staticmethod
    def track_covenant(
        db: Session,
        covenant_id: int,
        period_date: date,
    ) -> Optional[CovenantTracking]:
        """Crea un record de tracking para un covenant en una fecha."""
        covenant = db.query(Covenant).filter(Covenant.id == covenant_id).first()
        if not covenant:
            return None

        current_value, status, traffic_light, utilization = (
            CovenantService.evaluate_covenant(db, covenant, period_date)
        )

        tracking = CovenantTracking(
            covenant_id=covenant_id,
            period_date=period_date,
            current_value=current_value,
            limit_value=covenant.limit_value,
            utilization_pct=utilization,
            status=status,
            notes=f"Traffic light: {traffic_light}",
            calculated_by="SYSTEM",
        )
        db.add(tracking)
        db.commit()
        db.refresh(tracking)
        return tracking

    @staticmethod
    def get_covenant_status(
        db: Session,
        covenant_id: int,
        period_date: Optional[date] = None,
    ) -> dict:
        """Obtiene el status completo de un covenant."""
        if period_date is None:
            period_date = date.today()

        covenant = db.query(Covenant).filter(Covenant.id == covenant_id).first()
        if not covenant:
            return {}

        current_value, status, traffic_light, utilization = (
            CovenantService.evaluate_covenant(db, covenant, period_date)
        )

        # Historial de últimos 12 meses
        history = (
            db.query(CovenantTracking)
            .filter(CovenantTracking.covenant_id == covenant_id)
            .order_by(CovenantTracking.period_date.desc())
            .limit(12)
            .all()
        )

        return {
            "covenant": covenant,
            "current_value": current_value,
            "utilization_pct": utilization,
            "status": status,
            "traffic_light": traffic_light,
            "history": list(reversed(history)),
        }

    @staticmethod
    def batch_evaluate_covenants(
        db: Session,
        period_date: date,
    ) -> dict:
        """Evalúa todos los covenants activos en una fecha.

        Pre-fetches all tracking records in bulk and resolves the
        period_date once to avoid redundant queries per covenant.
        """
        covenants = (
            db.query(Covenant)
            .filter(Covenant.is_active == True)
            .all()
        )

        if not covenants:
            return {}

        # Resolve period_date ONCE for all covenants
        resolved_date = CovenantService._resolve_period_date(db, period_date)

        # Pre-fetch latest tracking for all covenants in bulk
        covenant_ids = [c.id for c in covenants]
        all_tracking = (
            db.query(CovenantTracking)
            .filter(CovenantTracking.covenant_id.in_(covenant_ids))
            .order_by(CovenantTracking.period_date.desc())
            .all()
        )

        # Build a map: covenant_id -> list of tracking (already ordered desc)
        tracking_by_covenant = {}
        for t in all_tracking:
            tracking_by_covenant.setdefault(t.covenant_id, []).append(t)

        results = {}
        for covenant in covenants:
            # Evaluate the covenant using the already-resolved date
            current_value, status, traffic_light, utilization = (
                CovenantService.evaluate_covenant(db, covenant, resolved_date)
            )

            # Get history from pre-fetched tracking (last 12)
            history = tracking_by_covenant.get(covenant.id, [])[:12]

            results[covenant.id] = {
                "covenant": covenant,
                "current_value": current_value,
                "utilization_pct": utilization,
                "status": status,
                "traffic_light": traffic_light,
                "history": list(reversed(history)),
            }

        return results
