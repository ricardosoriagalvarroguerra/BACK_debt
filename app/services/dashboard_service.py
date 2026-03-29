"""Servicio de dashboard - logica de calculo de metricas del portafolio.

Replica las formulas clave del Excel:
  - Spread PP = SUMPRODUCT(montos, spreads) / SUM(montos)
  - Plazo PP  = SUMPRODUCT(montos, plazos) / SUM(montos)
  - Tope de endeudamiento con semaforo
"""
from decimal import Decimal
from datetime import date
from typing import Optional, List
from sqlalchemy import func, case, and_, text, Integer
from sqlalchemy.orm import Session

from app.models.balance import Balance
from app.models.disbursement import Disbursement
from app.models.contract import Contract
from app.models.creditor import Creditor
from app.models.currency import Currency
from app.models.config import SystemConfig
from app.schemas.dashboard import (
    PortfolioSummary, DebtCeilingStatus, TimeSeriesPoint,
    TimeSeriesResponse, MaturityProfileItem, CompositionItem, TopInstrument,
    ContractingProfileItem, RiskSegment, RiskProfileResponse, InterestCostYear,
)
from app.services.cache_service import CacheService

CACHE_TTL = 300  # 5 minutes


class DashboardService:

    def __init__(self, db: Session):
        self.db = db

    def _get_latest_period(self, projected: Optional[bool] = None) -> Optional[date]:
        """Obtiene el periodo mas reciente que no supere la fecha actual."""
        today = date.today()
        q = self.db.query(func.max(Balance.period_date)).filter(
            Balance.outstanding_usd > 0,
            Balance.period_date <= today,
        )
        if projected is not None:
            q = q.filter(Balance.is_projected == projected)
        result = q.scalar()
        if result is None:
            # Fallback: si no hay periodos <= hoy, usar el mas cercano al futuro
            q2 = self.db.query(func.min(Balance.period_date)).filter(
                Balance.outstanding_usd > 0,
            )
            if projected is not None:
                q2 = q2.filter(Balance.is_projected == projected)
            result = q2.scalar()
        return result

    def get_summary(self, period_date: Optional[date] = None) -> PortfolioSummary:
        """Resumen ejecutivo del portafolio para un periodo dado."""
        if period_date is None:
            period_date = self._get_latest_period()

        cache_key = f"dashboard:summary:{period_date}"
        cached = CacheService.get(cache_key)
        if cached:
            return PortfolioSummary(**cached)

        # Query base: balances + disbursements + creditors
        rows = (
            self.db.query(
                Creditor.creditor_type,
                func.sum(Balance.outstanding_usd).label("total_usd"),
                func.sum(Balance.outstanding_usd * Balance.spread_bps).label("sum_usd_spread"),
                func.sum(Balance.outstanding_usd * Balance.residual_term_years).label("sum_usd_term"),
                func.count(func.distinct(Disbursement.id)).label("instruments"),
            )
            .join(Disbursement, Balance.disbursement_id == Disbursement.id)
            .join(Contract, Disbursement.contract_id == Contract.id)
            .join(Creditor, Contract.creditor_id == Creditor.id)
            .filter(
                Balance.period_date == period_date,
                Balance.outstanding_usd > 0,
                Balance.is_active == True,
            )
            .group_by(Creditor.creditor_type)
            .all()
        )

        ifd_usd = Decimal(0)
        market_usd = Decimal(0)
        ifd_spread_sum = Decimal(0)
        market_spread_sum = Decimal(0)
        ifd_term_sum = Decimal(0)
        market_term_sum = Decimal(0)
        ifd_count = 0
        market_count = 0

        for row in rows:
            total = row.total_usd or Decimal(0)
            spread_sum = row.sum_usd_spread or Decimal(0)
            term_sum = row.sum_usd_term or Decimal(0)
            count = row.instruments or 0

            if row.creditor_type == "IFD":
                ifd_usd = total
                ifd_spread_sum = spread_sum
                ifd_term_sum = term_sum
                ifd_count = count
            else:
                market_usd = total
                market_spread_sum = spread_sum
                market_term_sum = term_sum
                market_count = count

        total_usd = ifd_usd + market_usd
        total_spread_sum = ifd_spread_sum + market_spread_sum
        total_term_sum = ifd_term_sum + market_term_sum

        def safe_div(num, den):
            return round(num / den, 4) if den > 0 else Decimal(0)

        result = PortfolioSummary(
            period_date=period_date,
            total_outstanding_usd=round(total_usd, 2),
            ifd_outstanding_usd=round(ifd_usd, 2),
            market_outstanding_usd=round(market_usd, 2),
            weighted_avg_spread_bps=safe_div(total_spread_sum, total_usd),
            weighted_avg_term_years=safe_div(total_term_sum, total_usd),
            ifd_spread_bps=safe_div(ifd_spread_sum, ifd_usd),
            market_spread_bps=safe_div(market_spread_sum, market_usd),
            ifd_term_years=safe_div(ifd_term_sum, ifd_usd),
            market_term_years=safe_div(market_term_sum, market_usd),
            total_instruments=ifd_count + market_count,
            ifd_instruments=ifd_count,
            market_instruments=market_count,
        )
        CacheService.set(cache_key, result.model_dump(), CACHE_TTL)
        return result

    def get_debt_ceiling_status(self, period_date: Optional[date] = None) -> DebtCeilingStatus:
        """Estado del tope de endeudamiento con semaforo."""
        if period_date is None:
            period_date = self._get_latest_period()

        cache_key = f"dashboard:debt_ceiling:{period_date}"
        cached = CacheService.get(cache_key)
        if cached:
            return DebtCeilingStatus(**cached)

        total = (
            self.db.query(func.sum(Balance.outstanding_usd))
            .filter(
                Balance.period_date == period_date,
                Balance.is_active == True,
            )
            .scalar() or Decimal(0)
        )

        ceiling_row = self.db.query(SystemConfig).filter(SystemConfig.key == "debt_ceiling_usd_mm").first()
        bands_row = self.db.query(SystemConfig).filter(SystemConfig.key == "sensitivity_bands").first()

        ceiling = Decimal(str(ceiling_row.value)) if ceiling_row else Decimal(2500)
        bands = bands_row.value if bands_row else {}

        green_max = Decimal(str(bands.get("green_max", 1500)))
        yellow_max = Decimal(str(bands.get("yellow_max", 2100)))
        orange_max = Decimal(str(bands.get("orange_max", 2399)))

        pct = round(total * 100 / ceiling, 2) if ceiling > 0 else Decimal(0)

        if total >= ceiling:
            status, light = "INCUMPLIMIENTO", "ROJO"
        elif total >= orange_max:
            status, light = "CRITICO", "NARANJA"
        elif total >= yellow_max:
            status, light = "ALTO", "AMARILLO"
        elif total >= green_max:
            status, light = "MODERADO", "AMARILLO"
        else:
            status, light = "BAJO", "VERDE"

        result = DebtCeilingStatus(
            total_outstanding_usd=round(total, 2),
            ceiling_limit_usd=ceiling,
            utilization_pct=pct,
            status=status,
            traffic_light=light,
            available_capacity_usd=round(ceiling - total, 2),
        )
        CacheService.set(cache_key, result.model_dump(), CACHE_TTL)
        return result

    def get_time_series(
        self,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> TimeSeriesResponse:
        """Series temporales mensuales por tipo (IFD/Mercado/Total)."""
        cache_key = f"dashboard:time_series:{date_from}:{date_to}"
        cached = CacheService.get(cache_key)
        if cached:
            return TimeSeriesResponse(**cached)

        q = (
            self.db.query(
                Balance.period_date,
                Creditor.creditor_type,
                func.sum(Balance.outstanding_usd).label("total_usd"),
                case(
                    (func.sum(Balance.outstanding_usd) > 0,
                     func.sum(Balance.outstanding_usd * Balance.spread_bps) / func.sum(Balance.outstanding_usd)),
                    else_=0,
                ).label("spread_pp"),
                case(
                    (func.sum(Balance.outstanding_usd) > 0,
                     func.sum(Balance.outstanding_usd * Balance.residual_term_years) / func.sum(Balance.outstanding_usd)),
                    else_=0,
                ).label("term_pp"),
                func.sum(Balance.amortization_usd).label("amort_total"),
                func.bool_or(Balance.is_projected).label("is_proj"),
            )
            .join(Disbursement, Balance.disbursement_id == Disbursement.id)
            .join(Contract, Disbursement.contract_id == Contract.id)
            .join(Creditor, Contract.creditor_id == Creditor.id)
            .filter(Balance.outstanding_usd > 0, Balance.is_active == True)
        )

        if date_from:
            q = q.filter(Balance.period_date >= date_from)
        if date_to:
            q = q.filter(Balance.period_date <= date_to)

        rows = q.group_by(Balance.period_date, Creditor.creditor_type).order_by(
            Balance.period_date, Creditor.creditor_type
        ).all()

        ifd_series, market_series = [], []
        totals_map = {}

        for row in rows:
            point = TimeSeriesPoint(
                period_date=row.period_date,
                outstanding_usd=round(row.total_usd, 2),
                spread_bps=round(row.spread_pp, 4) if row.spread_pp else None,
                term_years=round(row.term_pp, 4) if row.term_pp else None,
                amortization_usd=round(row.amort_total, 2) if row.amort_total else None,
                is_projected=bool(row.is_proj),
            )
            if row.creditor_type == "IFD":
                ifd_series.append(point)
            else:
                market_series.append(point)

            # Acumular totales
            key = row.period_date
            if key not in totals_map:
                totals_map[key] = {
                    "usd": Decimal(0), "spread_sum": Decimal(0),
                    "term_sum": Decimal(0), "amort": Decimal(0), "proj": False,
                }
            totals_map[key]["usd"] += row.total_usd
            totals_map[key]["spread_sum"] += (row.total_usd * row.spread_pp) if row.spread_pp else Decimal(0)
            totals_map[key]["term_sum"] += (row.total_usd * row.term_pp) if row.term_pp else Decimal(0)
            totals_map[key]["amort"] += row.amort_total or Decimal(0)
            totals_map[key]["proj"] = totals_map[key]["proj"] or bool(row.is_proj)

        total_series = []
        for pd in sorted(totals_map.keys()):
            t = totals_map[pd]
            total_series.append(TimeSeriesPoint(
                period_date=pd,
                outstanding_usd=round(t["usd"], 2),
                spread_bps=round(t["spread_sum"] / t["usd"], 4) if t["usd"] > 0 else None,
                term_years=round(t["term_sum"] / t["usd"], 4) if t["usd"] > 0 else None,
                amortization_usd=round(t["amort"], 2),
                is_projected=t["proj"],
            ))

        result = TimeSeriesResponse(ifd=ifd_series, market=market_series, total=total_series)
        CacheService.set(cache_key, result.model_dump(), CACHE_TTL)
        return result

    def get_composition(self, period_date: Optional[date] = None) -> List[CompositionItem]:
        """Composicion del portafolio por acreedor."""
        if period_date is None:
            period_date = self._get_latest_period()

        cache_key = f"dashboard:composition:{period_date}"
        cached = CacheService.get(cache_key)
        if cached:
            return [CompositionItem(**item) for item in cached]

        total_q = (
            self.db.query(func.sum(Balance.outstanding_usd))
            .filter(Balance.period_date == period_date, Balance.is_active == True, Balance.outstanding_usd > 0)
            .scalar() or Decimal(1)
        )

        rows = (
            self.db.query(
                Creditor.creditor_type,
                Creditor.code.label("creditor_code"),
                Creditor.short_name.label("creditor_name"),
                Currency.code.label("currency_code"),
                func.count(func.distinct(Disbursement.id)).label("instrument_count"),
                func.sum(Balance.outstanding_usd).label("total_usd"),
            )
            .join(Disbursement, Balance.disbursement_id == Disbursement.id)
            .join(Contract, Disbursement.contract_id == Contract.id)
            .join(Creditor, Contract.creditor_id == Creditor.id)
            .join(Currency, Contract.currency_id == Currency.id)
            .filter(
                Balance.period_date == period_date,
                Balance.is_active == True,
                Balance.outstanding_usd > 0,
            )
            .group_by(Creditor.creditor_type, Creditor.code, Creditor.short_name, Currency.code)
            .order_by(func.sum(Balance.outstanding_usd).desc())
            .all()
        )

        result = [
            CompositionItem(
                creditor_type=r.creditor_type,
                creditor_code=r.creditor_code,
                creditor_name=r.creditor_name,
                currency_code=r.currency_code,
                instrument_count=r.instrument_count,
                total_outstanding_usd=round(r.total_usd, 2),
                pct_of_total=round(r.total_usd * 100 / total_q, 2),
            )
            for r in rows
        ]
        CacheService.set(cache_key, [item.model_dump() for item in result], CACHE_TTL)
        return result

    def get_top_instruments(self, period_date: Optional[date] = None, limit: int = 10) -> List[TopInstrument]:
        """Top N instrumentos por saldo."""
        if period_date is None:
            period_date = self._get_latest_period()

        cache_key = f"dashboard:top_instruments:{period_date}:{limit}"
        cached = CacheService.get(cache_key)
        if cached:
            return [TopInstrument(**item) for item in cached]

        rows = (
            self.db.query(
                Disbursement.disbursement_code,
                Disbursement.disbursement_name,
                Creditor.short_name.label("creditor_name"),
                Balance.outstanding_usd,
                Balance.spread_bps,
                Balance.residual_term_years,
                Creditor.creditor_type,
            )
            .join(Disbursement, Balance.disbursement_id == Disbursement.id)
            .join(Contract, Disbursement.contract_id == Contract.id)
            .join(Creditor, Contract.creditor_id == Creditor.id)
            .filter(
                Balance.period_date == period_date,
                Balance.outstanding_usd > 0,
            )
            .order_by(Balance.outstanding_usd.desc())
            .limit(limit)
            .all()
        )

        result = [
            TopInstrument(
                disbursement_code=r.disbursement_code,
                disbursement_name=r.disbursement_name,
                creditor_name=r.creditor_name,
                outstanding_usd=round(r.outstanding_usd, 2),
                spread_bps=round(r.spread_bps, 4) if r.spread_bps else None,
                residual_term_years=round(r.residual_term_years, 2) if r.residual_term_years else None,
                creditor_type=r.creditor_type,
            )
            for r in rows
        ]
        CacheService.set(cache_key, [item.model_dump() for item in result], CACHE_TTL)
        return result

    def get_maturity_profile(self) -> List[MaturityProfileItem]:
        """Perfil de amortización por año y acreedor.

        Usa la tabla balances.amortization_usd (amortización real calculada
        por período) en lugar de disbursements.amount_usd, para que los
        instrumentos AMORTIZABLE distribuyan su capital a lo largo de la vida
        del préstamo en vez de asignarlo todo al año de vencimiento.
        """
        cache_key = "dashboard:maturity_profile"
        cached = CacheService.get(cache_key)
        if cached:
            return [MaturityProfileItem(**item) for item in cached]

        rows = (
            self.db.query(
                func.extract("year", Balance.period_date).cast(Integer).label("year"),
                Creditor.creditor_type,
                Creditor.short_name.label("creditor_name"),
                func.count(func.distinct(Disbursement.id)).label("instrument_count"),
                func.sum(Balance.amortization_usd).label("total_usd"),
                func.avg(func.coalesce(Balance.spread_bps, Contract.spread_bps)).label("avg_spread"),
            )
            .join(Disbursement, Balance.disbursement_id == Disbursement.id)
            .join(Contract, Disbursement.contract_id == Contract.id)
            .join(Creditor, Contract.creditor_id == Creditor.id)
            .filter(
                Disbursement.status == "DESEMBOLSADO",
                Balance.period_date >= func.current_date(),
                Balance.amortization_usd > 0,
            )
            .group_by(
                func.extract("year", Balance.period_date),
                Creditor.creditor_type,
                Creditor.short_name,
            )
            .order_by(
                func.extract("year", Balance.period_date),
                Creditor.creditor_type,
            )
            .all()
        )

        result = [
            MaturityProfileItem(
                year=int(r.year),
                creditor_type=r.creditor_type,
                creditor_name=r.creditor_name,
                instrument_count=r.instrument_count,
                total_amount_usd=round(r.total_usd, 2),
                avg_spread_bps=round(r.avg_spread, 2) if r.avg_spread else None,
            )
            for r in rows
        ]
        CacheService.set(cache_key, [item.model_dump() for item in result], CACHE_TTL)
        return result

    def get_contracting_profile(self) -> List[ContractingProfileItem]:
        """Spread PP y Plazo PP de contratación por año y tipo de acreedor.

        Año de contratación = año del disbursement_date.
        Spread PP = SUMPRODUCT(amount_usd, spread_bps) / SUM(amount_usd)
        Plazo PP  = SUMPRODUCT(amount_usd, (maturity_date - disbursement_date)/365.25) / SUM(amount_usd)
        """
        cache_key = "dashboard:contracting_profile"
        cached = CacheService.get(cache_key)
        if cached:
            return [ContractingProfileItem(**item) for item in cached]

        from sqlalchemy import Numeric as SANumeric, cast as sa_cast
        spread_expr = func.coalesce(Disbursement.spread_bps_override, Contract.spread_bps)
        # In PostgreSQL, DATE - DATE returns integer days
        tenor_days = func.cast(
            Disbursement.maturity_date - Disbursement.disbursement_date, SANumeric
        )
        tenor_years_expr = tenor_days / 365.25

        rows = (
            self.db.query(
                func.extract("year", Disbursement.disbursement_date).cast(Integer).label("year"),
                Creditor.creditor_type,
                (
                    func.sum(Disbursement.amount_usd * spread_expr)
                    / func.nullif(func.sum(Disbursement.amount_usd), 0)
                ).label("wavg_spread"),
                (
                    func.sum(Disbursement.amount_usd * tenor_years_expr)
                    / func.nullif(func.sum(Disbursement.amount_usd), 0)
                ).label("wavg_tenor"),
                func.sum(Disbursement.amount_usd).label("total_usd"),
                func.count().label("instrument_count"),
            )
            .join(Contract, Disbursement.contract_id == Contract.id)
            .join(Creditor, Contract.creditor_id == Creditor.id)
            .filter(Disbursement.status == "DESEMBOLSADO")
            .group_by(
                func.extract("year", Disbursement.disbursement_date),
                Creditor.creditor_type,
            )
            .order_by(
                func.extract("year", Disbursement.disbursement_date),
                Creditor.creditor_type,
            )
            .all()
        )

        result = [
            ContractingProfileItem(
                year=int(r.year),
                creditor_type=r.creditor_type,
                wavg_spread_bps=round(r.wavg_spread, 2) if r.wavg_spread else None,
                wavg_tenor_years=round(r.wavg_tenor, 2) if r.wavg_tenor else None,
                total_amount_usd=round(r.total_usd, 2),
                instrument_count=r.instrument_count,
            )
            for r in rows
        ]
        CacheService.set(cache_key, [item.model_dump() for item in result], CACHE_TTL)
        return result

    # ---- Risk profile ----

    def get_risk_profile(self, period_date: Optional[date] = None) -> "RiskProfileResponse":
        """Perfil de riesgo estructural: moneda, tipo tasa, amortizacion, plazo."""
        if period_date is None:
            period_date = self._get_latest_period()

        cache_key = f"dashboard:risk_profile:{period_date}"
        cached = CacheService.get(cache_key)
        if cached:
            return RiskProfileResponse(**cached)

        rows = (
            self.db.query(
                Currency.code.label("currency_code"),
                Contract.interest_rate_type,
                Contract.amortization_type,
                Balance.outstanding_usd,
                Balance.residual_term_years,
            )
            .join(Disbursement, Balance.disbursement_id == Disbursement.id)
            .join(Contract, Disbursement.contract_id == Contract.id)
            .join(Currency, Contract.currency_id == Currency.id)
            .filter(
                Balance.period_date == period_date,
                Balance.is_active == True,
                Balance.outstanding_usd > 0,
            )
            .all()
        )

        total_usd = sum(float(r.outstanding_usd) for r in rows) or 1.0

        def _aggregate(key_fn):
            agg: dict = {}
            for r in rows:
                k = key_fn(r)
                if k not in agg:
                    agg[k] = {"amount": 0.0, "count": 0}
                agg[k]["amount"] += float(r.outstanding_usd)
                agg[k]["count"] += 1
            return sorted(
                [RiskSegment(label=k, amount_usd=round(v["amount"], 2),
                             pct=round(v["amount"] / total_usd * 100, 1),
                             instrument_count=v["count"])
                 for k, v in agg.items()],
                key=lambda s: float(s.amount_usd), reverse=True,
            )

        currency_exposure = _aggregate(lambda r: r.currency_code)
        rate_type = _aggregate(lambda r: r.interest_rate_type or "NO DEFINIDO")
        amortization_type = _aggregate(lambda r: r.amortization_type or "NO DEFINIDO")

        # Residual term buckets
        buckets = [("< 1 ano", 0, 1), ("1-3 anos", 1, 3), ("3-5 anos", 3, 5),
                    ("5-10 anos", 5, 10), ("10+ anos", 10, 999)]
        term_agg = {b[0]: {"amount": 0.0, "count": 0} for b in buckets}
        for r in rows:
            t = float(r.residual_term_years) if r.residual_term_years else 0
            for label, lo, hi in buckets:
                if lo <= t < hi:
                    term_agg[label]["amount"] += float(r.outstanding_usd)
                    term_agg[label]["count"] += 1
                    break
        residual_term = [
            RiskSegment(label=lb, amount_usd=round(v["amount"], 2),
                        pct=round(v["amount"] / total_usd * 100, 1),
                        instrument_count=v["count"])
            for lb, v in term_agg.items() if v["count"] > 0
        ]

        result = RiskProfileResponse(
            period_date=period_date,
            currency_exposure=currency_exposure,
            rate_type=rate_type,
            amortization_type=amortization_type,
            residual_term=residual_term,
        )
        CacheService.set(cache_key, result.model_dump(), CACHE_TTL)
        return result

    # ---- Interest cost analytics ----

    def get_interest_cost(self, source: str = None) -> List[InterestCostYear]:
        """Costo de deuda anual: interes, principal, servicio, spread PP por ano."""
        cache_key = f"dashboard:interest_cost:{source or 'all'}"
        cached = CacheService.get(cache_key)
        if cached:
            return [InterestCostYear(**item) for item in cached]

        q = (
            self.db.query(
                func.extract("year", Balance.period_date).cast(Integer).label("year"),
                func.sum(func.coalesce(Balance.interest_usd, 0)).label("interest"),
                func.sum(func.coalesce(Balance.amortization_usd, 0)).label("principal"),
                func.sum(func.coalesce(Balance.debt_service_usd, 0)).label("service"),
                case(
                    (func.sum(Balance.outstanding_usd) > 0,
                     func.sum(Balance.outstanding_usd * Balance.spread_bps) / func.sum(Balance.outstanding_usd)),
                    else_=None,
                ).label("wavg_spread"),
                func.sum(Balance.outstanding_usd).label("avg_outstanding"),
                func.count(func.distinct(Balance.disbursement_id)).label("instruments"),
                func.bool_or(Balance.is_projected).label("is_proj"),
            )
            .join(Disbursement, Balance.disbursement_id == Disbursement.id)
            .join(Contract, Disbursement.contract_id == Contract.id)
            .join(Creditor, Contract.creditor_id == Creditor.id)
            .filter(Balance.is_active == True, Balance.outstanding_usd > 0)
        )

        if source and source.upper() in ("IFD", "MERCADO"):
            q = q.filter(Creditor.creditor_type == source.upper())

        rows = (
            q.group_by(func.extract("year", Balance.period_date))
            .order_by(func.extract("year", Balance.period_date))
            .all()
        )

        result = [
            InterestCostYear(
                year=int(r.year),
                interest_usd=round(r.interest, 2),
                principal_usd=round(r.principal, 2),
                debt_service_usd=round(r.service, 2),
                wavg_spread_bps=round(r.wavg_spread, 2) if r.wavg_spread else None,
                avg_outstanding_usd=round(r.avg_outstanding, 2),
                instrument_count=r.instruments,
                is_projected=bool(r.is_proj),
            )
            for r in rows
        ]
        CacheService.set(cache_key, [item.model_dump() for item in result], CACHE_TTL)
        return result
