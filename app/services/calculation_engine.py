"""Motor de cálculos financieros - replica las fórmulas del Excel."""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_, literal

from app.models.balance import Balance
from app.models.disbursement import Disbursement
from app.models.contract import Contract
from app.models.creditor import Creditor
from app.models.config import SystemConfig


class CalculationEngine:
    """Replica exacta de las fórmulas del Excel de endeudamiento."""

    DEBT_CEILING_USD_MM = 2500.0  # Tope de endeudamiento

    # Bandas de sensibilidad (semáforo)
    SENSITIVITY_BANDS = {
        "VERDE": (0, 1500),
        "AMARILLO": (1500, 2100),
        "NARANJA": (2100, 2400),
        "ROJO": (2400, float("inf")),
    }

    @staticmethod
    def total_outstanding(
        db: Session,
        period_date: date,
        creditor_type: Optional[str] = None,
    ) -> Decimal:
        """
        Saldo circulante total en USD para una fecha.
        Equivale a SUM de circulante en el Excel.
        """
        query = (
            db.query(func.coalesce(func.sum(Balance.outstanding_usd), 0))
            .join(Disbursement, Balance.disbursement_id == Disbursement.id)
        )
        if creditor_type:
            query = query.join(Contract, Disbursement.contract_id == Contract.id) \
                         .join(Creditor, Contract.creditor_id == Creditor.id) \
                         .filter(Creditor.creditor_type == creditor_type)
        query = query.filter(Balance.period_date == period_date, Balance.is_active == True)
        result = query.scalar()
        return Decimal(str(result)) if result else Decimal("0")

    @staticmethod
    def weighted_average_spread(
        db: Session,
        period_date: date,
        creditor_type: Optional[str] = None,
    ) -> Optional[Decimal]:
        """
        Spread Promedio Ponderado (bps).
        Excel formula: SUMPRODUCT(montos, spreads) / SUM(montos)
        Uses SQL aggregation instead of loading rows into Python.
        """
        query = (
            db.query(
                func.sum(Balance.outstanding_usd * Balance.spread_bps).label("sum_product"),
                func.sum(Balance.outstanding_usd).label("sum_montos"),
            )
            .join(Disbursement, Balance.disbursement_id == Disbursement.id)
        )
        if creditor_type:
            query = query.join(Contract, Disbursement.contract_id == Contract.id) \
                         .join(Creditor, Contract.creditor_id == Creditor.id) \
                         .filter(Creditor.creditor_type == creditor_type)
        query = query.filter(
            Balance.period_date == period_date,
            Balance.is_active == True,
            Balance.outstanding_usd > 0,
            Balance.spread_bps.isnot(None),
        )
        row = query.first()
        if not row or not row.sum_montos or row.sum_montos == 0:
            return None
        return Decimal(str(row.sum_product)) / Decimal(str(row.sum_montos))

    @staticmethod
    def weighted_average_term(
        db: Session,
        period_date: date,
        creditor_type: Optional[str] = None,
    ) -> Optional[Decimal]:
        """
        Plazo Promedio Ponderado (años).
        Excel formula: SUMPRODUCT(montos, plazos_residuales) / SUM(montos)
        Uses SQL aggregation instead of loading rows into Python.
        """
        query = (
            db.query(
                func.sum(Balance.outstanding_usd * Balance.residual_term_years).label("sum_product"),
                func.sum(Balance.outstanding_usd).label("sum_montos"),
            )
            .join(Disbursement, Balance.disbursement_id == Disbursement.id)
        )
        if creditor_type:
            query = query.join(Contract, Disbursement.contract_id == Contract.id) \
                         .join(Creditor, Contract.creditor_id == Creditor.id) \
                         .filter(Creditor.creditor_type == creditor_type)
        query = query.filter(
            Balance.period_date == period_date,
            Balance.is_active == True,
            Balance.outstanding_usd > 0,
            Balance.residual_term_years.isnot(None),
        )
        row = query.first()
        if not row or not row.sum_montos or row.sum_montos == 0:
            return None
        return Decimal(str(row.sum_product)) / Decimal(str(row.sum_montos))

    @staticmethod
    def debt_ceiling_check(
        db: Session,
        period_date: date,
        scenario_additions: Decimal = Decimal("0"),
    ) -> Dict:
        """
        Evalúa el tope de endeudamiento con semáforo.
        Returns: {total, ceiling, utilization_pct, status, traffic_light, available}
        """
        # Get ceiling from system config
        ceiling_config = db.query(SystemConfig).filter(
            SystemConfig.key == "debt_ceiling_usd_mm"
        ).first()
        ceiling = Decimal(str(ceiling_config.value)) if ceiling_config else Decimal(str(CalculationEngine.DEBT_CEILING_USD_MM))

        total = CalculationEngine.total_outstanding(db, period_date) + scenario_additions
        utilization = (total / ceiling * 100) if ceiling > 0 else Decimal("0")
        available = ceiling - total

        # Determine traffic light
        total_float = float(total)
        traffic_light = "VERDE"
        for color, (low, high) in CalculationEngine.SENSITIVITY_BANDS.items():
            if low <= total_float < high:
                traffic_light = color
                break
        if total_float >= 2400:
            traffic_light = "ROJO"

        return {
            "total_outstanding_usd": float(total),
            "ceiling_limit_usd": float(ceiling),
            "utilization_pct": float(utilization),
            "status": "DENTRO_LIMITE" if total <= ceiling else "EXCEDE_LIMITE",
            "traffic_light": traffic_light,
            "available_capacity_usd": float(available),
        }

    @staticmethod
    def portfolio_metrics(
        db: Session,
        period_date: date,
    ) -> Dict:
        """
        Métricas completas del portafolio para una fecha.
        Consolidated into a single GROUP BY query instead of 9+ separate queries.
        """
        # Single query: aggregate by creditor_type
        rows = (
            db.query(
                Creditor.creditor_type,
                func.coalesce(func.sum(Balance.outstanding_usd), 0).label("total_outstanding"),
                func.sum(
                    case(
                        (Balance.spread_bps.isnot(None), Balance.outstanding_usd * Balance.spread_bps),
                        else_=0,
                    )
                ).label("spread_weight_sum"),
                func.sum(
                    case(
                        (Balance.spread_bps.isnot(None), Balance.outstanding_usd),
                        else_=0,
                    )
                ).label("spread_weight_denom"),
                func.sum(
                    case(
                        (Balance.residual_term_years.isnot(None), Balance.outstanding_usd * Balance.residual_term_years),
                        else_=0,
                    )
                ).label("term_weight_sum"),
                func.sum(
                    case(
                        (Balance.residual_term_years.isnot(None), Balance.outstanding_usd),
                        else_=0,
                    )
                ).label("term_weight_denom"),
                func.count(Disbursement.id).label("instrument_count"),
            )
            .join(Disbursement, Balance.disbursement_id == Disbursement.id)
            .join(Contract, Disbursement.contract_id == Contract.id)
            .join(Creditor, Contract.creditor_id == Creditor.id)
            .filter(
                Balance.period_date == period_date,
                Balance.is_active == True,
                Balance.outstanding_usd > 0,
            )
            .group_by(Creditor.creditor_type)
            .all()
        )

        # Parse results by creditor type
        metrics_by_type = {}
        for row in rows:
            metrics_by_type[row.creditor_type] = row

        def _get_metric(ct, attr):
            r = metrics_by_type.get(ct)
            return Decimal(str(getattr(r, attr))) if r else Decimal(0)

        def _safe_div(num, den):
            return float(num / den) if den and den > 0 else 0

        ifd = _get_metric("IFD", "total_outstanding")
        market = _get_metric("MERCADO", "total_outstanding")
        total = ifd + market

        ifd_spread_sum = _get_metric("IFD", "spread_weight_sum")
        ifd_spread_den = _get_metric("IFD", "spread_weight_denom")
        market_spread_sum = _get_metric("MERCADO", "spread_weight_sum")
        market_spread_den = _get_metric("MERCADO", "spread_weight_denom")
        total_spread_sum = ifd_spread_sum + market_spread_sum
        total_spread_den = ifd_spread_den + market_spread_den

        ifd_term_sum = _get_metric("IFD", "term_weight_sum")
        ifd_term_den = _get_metric("IFD", "term_weight_denom")
        market_term_sum = _get_metric("MERCADO", "term_weight_sum")
        market_term_den = _get_metric("MERCADO", "term_weight_denom")
        total_term_sum = ifd_term_sum + market_term_sum
        total_term_den = ifd_term_den + market_term_den

        ifd_instruments = int(_get_metric("IFD", "instrument_count"))
        market_instruments = int(_get_metric("MERCADO", "instrument_count"))

        ceiling = CalculationEngine.debt_ceiling_check(db, period_date)

        return {
            "period_date": period_date.isoformat(),
            "total_outstanding_usd": float(total),
            "ifd_outstanding_usd": float(ifd),
            "market_outstanding_usd": float(market),
            "weighted_avg_spread_bps": _safe_div(total_spread_sum, total_spread_den),
            "weighted_avg_term_years": _safe_div(total_term_sum, total_term_den),
            "ifd_spread_bps": _safe_div(ifd_spread_sum, ifd_spread_den),
            "market_spread_bps": _safe_div(market_spread_sum, market_spread_den),
            "ifd_term_years": _safe_div(ifd_term_sum, ifd_term_den),
            "market_term_years": _safe_div(market_term_sum, market_term_den),
            "total_instruments": ifd_instruments + market_instruments,
            "ifd_instruments": ifd_instruments,
            "market_instruments": market_instruments,
            "ceiling": ceiling,
        }

    @staticmethod
    def interest_calculation(
        outstanding_usd: Decimal,
        spread_bps: Decimal,
        base_rate_bps: Decimal = Decimal("0"),
        days_in_period: int = 30,
        day_count: int = 360,
    ) -> Decimal:
        """
        Calcula interés para un período.
        Interés = Outstanding * (base_rate + spread) / 10000 * days / day_count
        """
        total_rate_bps = base_rate_bps + spread_bps
        annual_rate = total_rate_bps / Decimal("10000")
        interest = outstanding_usd * annual_rate * Decimal(str(days_in_period)) / Decimal(str(day_count))
        return interest.quantize(Decimal("0.000001"))

    @staticmethod
    def amortization_schedule(
        amount_usd: Decimal,
        amort_type: str,
        num_periods: int,
        maturity_date: date,
        start_date: date,
        grace_periods: int = 0,
    ) -> List[Dict]:
        """
        Genera calendario de amortización.
        BULLET: todo al vencimiento
        AMORTIZABLE: cuotas iguales de principal
        """
        schedule = []

        if amort_type == "BULLET":
            # For bullet, entire principal at maturity
            for i in range(num_periods):
                period_num = i + 1
                principal = amount_usd if period_num == num_periods else Decimal("0")
                schedule.append({
                    "period": period_num,
                    "principal_usd": float(principal),
                    "is_grace": period_num <= grace_periods,
                })
        elif amort_type in ("AMORTIZABLE",):
            # Linear: equal principal payments after grace period
            effective_periods = num_periods - grace_periods
            if effective_periods <= 0:
                effective_periods = 1
            payment_per_period = amount_usd / Decimal(str(effective_periods))

            for i in range(num_periods):
                period_num = i + 1
                is_grace = period_num <= grace_periods
                principal = Decimal("0") if is_grace else payment_per_period
                schedule.append({
                    "period": period_num,
                    "principal_usd": float(principal),
                    "is_grace": is_grace,
                })

        return schedule

    @staticmethod
    def composition_by_creditor(
        db: Session,
        period_date: date,
    ) -> List[Dict]:
        """Composición del portafolio por acreedor."""
        query = (
            db.query(
                Creditor.creditor_type,
                Creditor.code.label("creditor_code"),
                Creditor.short_name.label("creditor_name"),
                func.count(Disbursement.id).label("instrument_count"),
                func.coalesce(func.sum(Balance.outstanding_usd), 0).label("total_outstanding"),
            )
            .join(Contract, Creditor.id == Contract.creditor_id)
            .join(Disbursement, Contract.id == Disbursement.contract_id)
            .join(Balance, Disbursement.id == Balance.disbursement_id)
            .filter(
                Balance.period_date == period_date,
                Balance.is_active == True,
                Balance.outstanding_usd > 0,
            )
            .group_by(Creditor.creditor_type, Creditor.code, Creditor.short_name)
            .order_by(func.sum(Balance.outstanding_usd).desc())
        )
        rows = query.all()

        grand_total = sum(float(r.total_outstanding) for r in rows)

        return [
            {
                "creditor_type": r.creditor_type,
                "creditor_code": r.creditor_code,
                "creditor_name": r.creditor_name,
                "instrument_count": r.instrument_count,
                "total_outstanding_usd": float(r.total_outstanding),
                "pct_of_total": round(float(r.total_outstanding) / grand_total * 100, 2) if grand_total > 0 else 0,
            }
            for r in rows
        ]

    @staticmethod
    def maturity_profile(
        db: Session,
    ) -> List[Dict]:
        """Perfil de vencimientos por año."""
        query = (
            db.query(
                func.extract("year", Disbursement.maturity_date).label("year"),
                Creditor.creditor_type,
                Creditor.short_name.label("creditor_name"),
                func.count(Disbursement.id).label("instrument_count"),
                func.coalesce(func.sum(Disbursement.amount_usd), 0).label("total_amount"),
                func.avg(
                    case(
                        (Disbursement.spread_bps_override.isnot(None), Disbursement.spread_bps_override),
                        else_=Contract.spread_bps,
                    )
                ).label("avg_spread"),
            )
            .join(Contract, Disbursement.contract_id == Contract.id)
            .join(Creditor, Contract.creditor_id == Creditor.id)
            .filter(Disbursement.status == "DESEMBOLSADO")
            .group_by(
                func.extract("year", Disbursement.maturity_date),
                Creditor.creditor_type,
                Creditor.short_name,
            )
            .order_by(func.extract("year", Disbursement.maturity_date))
        )
        rows = query.all()

        return [
            {
                "year": int(r.year),
                "creditor_type": r.creditor_type,
                "creditor_name": r.creditor_name,
                "instrument_count": r.instrument_count,
                "total_amount_usd": float(r.total_amount),
                "avg_spread_bps": float(r.avg_spread) if r.avg_spread else None,
            }
            for r in rows
        ]
