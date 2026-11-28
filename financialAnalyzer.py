from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

import pandas as pd


def _to_float(val: Any) -> float:
    """Safely convert any numeric or string value to float, handling currency symbols and commas."""
    if val is None or pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(',', '').replace('₹', '').replace('Rs.', '').replace('Rs', '').strip()
    if not s or s in ('-', '--', 'N/A', 'NA', 'None', 'null'):
        return 0.0
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


class FinancialAnalyzer:
    """A Mutual Fund Advisor tool that parses a client's Excel portfolio."""

    def __init__(self, excel_path: str | Path):
        self.excel_path = Path(excel_path)
        if not self.excel_path.exists():
            raise FileNotFoundError(f"Excel file not found at: {self.excel_path}")
        
        # Parse the entire Excel workbook
        self.portfolio_data = self._parse_workbook()

    def _clean_val(self, val: Any) -> Any:
        if pd.isna(val):
            return None
        if isinstance(val, (int, float)):
            return round(val, 2)
        return str(val).strip()

    def _parse_workbook(self) -> Dict[str, Any]:
        xl = pd.ExcelFile(self.excel_path)
        data = {}

        # 1. Parse Holder Wise summary
        if 'Holder Wise' in xl.sheet_names:
            df = xl.parse('Holder Wise', header=None)
            if len(df) > 2:
                headers = [str(x).strip() for x in df.iloc[1].tolist()]
                holders = []
                for idx in range(2, len(df)):
                    row = df.iloc[idx].tolist()
                    if pd.isna(row[0]):
                        continue
                    holder_info = {headers[i]: self._clean_val(row[i]) for i in range(len(headers)) if i < len(row)}
                    holders.append(holder_info)
                data['holders'] = holders

        # 2. Parse Active Sip
        if 'Active Sip' in xl.sheet_names:
            df = xl.parse('Active Sip', header=None)
            if len(df) > 2:
                headers = [str(x).strip() for x in df.iloc[1].tolist()]
                sips = []
                for idx in range(2, len(df)):
                    row = df.iloc[idx].tolist()
                    if pd.isna(row[0]) or str(row[0]).lower() == 'total':
                        continue
                    sip_info = {headers[i]: self._clean_val(row[i]) for i in range(len(headers)) if i < len(row)}
                    sips.append(sip_info)
                data['active_sips'] = sips

        # 3. Parse Folio Wise details (where detailed schemes are listed for each holder)
        if 'Folio Wise' in xl.sheet_names:
            df = xl.parse('Folio Wise', header=None)
            current_holder = None
            headers = None
            schemes = {}
            
            # Extract known holders for comparison
            known_holders = []
            if 'holders' in data:
                known_holders = [" ".join(h.get('Holder Name', '').lower().split()) for h in data['holders'] if h.get('Holder Name')]
            
            for idx, row in df.iterrows():
                row_vals = list(row.values)
                non_na_vals = [x for x in row_vals if not pd.isna(x)]
                if len(non_na_vals) == 0:
                    continue
                
                # Check if this row lists a family member/holder name
                if len(non_na_vals) == 1:
                    val_str = str(non_na_vals[0]).strip()
                    val_norm = " ".join(val_str.lower().split())
                    
                    is_holder = False
                    if known_holders:
                        is_holder = val_norm in known_holders or any(val_norm in kh or kh in val_norm for kh in known_holders)
                    else:
                        is_holder = "valuation report" not in val_norm and "portfolio status" not in val_norm and "period" not in val_norm
                        
                    if is_holder:
                        current_holder = val_str
                        if 'holders' in data:
                            for h in data['holders']:
                                h_name = h.get('Holder Name')
                                if h_name and " ".join(h_name.lower().split()) == val_norm:
                                    current_holder = h_name
                                    break
                        schemes[current_holder] = []
                        headers = None
                        continue
                
                # Column headers row
                if 'Scheme Name' in row_vals:
                    headers = [str(x).strip() for x in row_vals]
                    continue
                    
                if current_holder and headers:
                    if str(row_vals[0]).lower() == 'total':
                        continue
                    scheme_info = {}
                    for i, val in enumerate(row_vals):
                        if i < len(headers):
                            h = headers[i]
                            if pd.isna(h):
                                continue
                            scheme_info[h] = self._clean_val(val)
                    if scheme_info.get('Scheme Name'):
                        schemes[current_holder].append(scheme_info)
            data['portfolio_schemes'] = schemes

        # 4. Parse Category Wise
        if 'Category Wise' in xl.sheet_names:
            df = xl.parse('Category Wise', header=None)
            if len(df) > 2:
                headers = [str(x).strip() for x in df.iloc[1].tolist()]
                categories = []
                for idx in range(2, len(df)):
                    row = df.iloc[idx].tolist()
                    if pd.isna(row[0]):
                        continue
                    cat_info = {headers[i]: self._clean_val(row[i]) for i in range(len(headers)) if i < len(row)}
                    categories.append(cat_info)
                data['categories'] = categories

        # 5. Parse AMC Wise
        if 'AMC Wise' in xl.sheet_names:
            df = xl.parse('AMC Wise', header=None)
            if len(df) > 2:
                headers = [str(x).strip() for x in df.iloc[1].tolist()]
                amcs = []
                for idx in range(2, len(df)):
                    row = df.iloc[idx].tolist()
                    if pd.isna(row[0]):
                        continue
                    amc_info = {headers[i]: self._clean_val(row[i]) for i in range(len(headers)) if i < len(row)}
                    amcs.append(amc_info)
                data['amc_wise'] = amcs

        # 6. Parse Scheme Wise
        if 'Scheme Wise' in xl.sheet_names:
            df = xl.parse('Scheme Wise', header=None)
            if len(df) > 2:
                headers = [str(x).strip() for x in df.iloc[1].tolist()]
                schemes_list = []
                for idx in range(2, len(df)):
                    row = df.iloc[idx].tolist()
                    if pd.isna(row[0]) or str(row[0]).lower() == 'total':
                        continue
                    s_info = {headers[i]: self._clean_val(row[i]) for i in range(len(headers)) if i < len(row)}
                    schemes_list.append(s_info)
                data['scheme_wise'] = schemes_list

        # 7. Parse Transaction Wise
        if 'Transaction Wise' in xl.sheet_names:
            df = xl.parse('Transaction Wise', header=None)
            if len(df) > 1:
                headers = [str(x).strip() for x in df.iloc[0].tolist()]
                tx_list = []
                for idx in range(1, len(df)):
                    row = df.iloc[idx].tolist()
                    if pd.isna(row[0]):
                        continue
                    tx_info = {headers[i]: self._clean_val(row[i]) for i in range(len(headers)) if i < len(row)}
                    tx_list.append(tx_info)
                data['transactions'] = tx_list

        return data

    def _generate_compact_summary(self) -> str:
        """Create a compact summary for the LLM system prompt to reduce token count and speed up responses."""
        lines = []
        lines.append("PORTFOLIO DATA:")

        # Holder summary (compact)
        if 'holders' in self.portfolio_data:
            lines.append("\nHOLDERS:")
            for h in self.portfolio_data['holders']:
                lines.append(f"  {h.get('Holder Name')}: SIP=Rs.{h.get('SIP') or 0}, Cost=Rs.{h.get('Cost of Investment') or 0}, Value=Rs.{h.get('Current Value') or 0}, XIRR={h.get('XIRR') or 0}%")

        # Active SIPs (compact)
        if 'active_sips' in self.portfolio_data:
            lines.append("\nACTIVE SIPs:")
            for s in self.portfolio_data['active_sips']:
                lines.append(f"  {s.get('Holder Name')} | {s.get('Scheme Name')} | Rs.{s.get('Amount')} | {s.get('Frequency')}")

        # Categories (compact)
        if 'categories' in self.portfolio_data:
            lines.append("\nCATEGORIES:")
            for c in self.portfolio_data['categories']:
                lines.append(f"  {c.get('Category Name')}: Cost=Rs.{c.get('Cost of Investment') or 0}, Value=Rs.{c.get('Current Value') or 0}, XIRR={c.get('XIRR') or 0}%")

        # Schemes (compact - one line per scheme)
        if 'portfolio_schemes' in self.portfolio_data:
            lines.append("\nSCHEMES:")
            for holder, schemes in self.portfolio_data['portfolio_schemes'].items():
                lines.append(f"  [{holder}]")
                for s in schemes:
                    lines.append(
                        f"    {s.get('Scheme Name')}: Cost=Rs.{s.get('Cost of Investment') or 0}, "
                        f"Value=Rs.{s.get('Current value') or 0}, XIRR={s.get('XIRR') or 0}%, "
                        f"Units={s.get('Units')}, Nominee={s.get('Nominee') or 'N/A'}"
                    )

        return "\n".join(lines)

    def _generate_compact_summary_for_holder(self, holder_name: str) -> str:
        """Create a compact summary filtered to a specific holder only."""
        lines = []
        lines.append(f"PORTFOLIO DATA FOR: {holder_name.upper()}")

        # Holder summary (only the matched holder)
        if 'holders' in self.portfolio_data:
            lines.append("\nHOLDER SUMMARY:")
            for h in self.portfolio_data['holders']:
                if holder_name.lower() in str(h.get('Holder Name', '')).lower():
                    lines.append(
                        f"  Name: {h.get('Holder Name')}\n"
                        f"  SIP=Rs.{h.get('SIP') or 0}, "
                        f"Cost=Rs.{h.get('Cost of Investment') or 0}, "
                        f"Current Value=Rs.{h.get('Current Value') or 0}, "
                        f"XIRR={h.get('XIRR') or 0}%, "
                        f"ABS={h.get('ABS') or 0}%"
                    )

        # Active SIPs (only for this holder)
        if 'active_sips' in self.portfolio_data:
            holder_sips = [
                s for s in self.portfolio_data['active_sips']
                if holder_name.lower() in str(s.get('Holder Name', '')).lower()
            ]
            if holder_sips:
                lines.append("\nACTIVE SIPs:")
                for s in holder_sips:
                    lines.append(
                        f"  {s.get('Scheme Name')} | Rs.{s.get('Amount')} | "
                        f"{s.get('Frequency')} | Date: {s.get('Sip Date')}"
                    )

        # Schemes (only for this holder)
        if 'portfolio_schemes' in self.portfolio_data:
            lines.append("\nSCHEMES:")
            for holder_key, schemes in self.portfolio_data['portfolio_schemes'].items():
                if holder_name.lower() in holder_key.lower():
                    for s in schemes:
                        lines.append(
                            f"  {s.get('Scheme Name')}: Cost=Rs.{s.get('Cost of Investment') or 0}, "
                            f"Value=Rs.{s.get('Current value') or 0}, XIRR={s.get('XIRR') or 0}%, "
                            f"Units={s.get('Units')}, Nominee={s.get('Nominee') or 'N/A'}"
                        )

        return "\n".join(lines)

    def get_valuation_date(self) -> str:
        """Extract portfolio valuation date from filename or transactions."""
        # 1. From filename (e.g. Portfolio_Name_2026-11-23.xls)
        m = re.search(r'(\d{4}-\d{2}-\d{2})', self.excel_path.name)
        if m:
            try:
                dt = pd.to_datetime(m.group(1))
                return dt.strftime('%d %b %Y')
            except Exception:
                pass

        # 2. From Transaction Wise Index Date or Date
        txs = self.portfolio_data.get('transactions', [])
        if txs:
            for key in ('Index Date', 'Date'):
                for t in reversed(txs):
                    val = t.get(key)
                    if val:
                        try:
                            dt = pd.to_datetime(str(val), format='%d/%m/%Y', errors='coerce')
                            if pd.notna(dt):
                                return dt.strftime('%d %b %Y')
                        except Exception:
                            pass

        return datetime.now().strftime('%d %b %Y')

    def _detect_fund_house(self, scheme_name: str, amc_list: List[Dict[str, Any]]) -> str:
        """Map scheme name to its AMC/Fund House name."""
        s_upper = scheme_name.upper()
        for a in amc_list:
            aname = str(a.get('AMC Name', '')).strip()
            first_word = aname.split()[0].upper() if aname else ""
            if first_word and first_word in s_upper:
                return aname.title()

        KNOWN_AMCS = [
            ("BANDHAN", "Bandhan Mutual Fund"),
            ("BANK OF INDIA", "Bank of India Mutual Fund"),
            ("BOI", "Bank of India Mutual Fund"),
            ("CANARA ROB", "Canara Robeco Mutual Fund"),
            ("EDELWEISS", "Edelweiss Mutual Fund"),
            ("FRANKLIN", "Franklin Templeton Mutual Fund"),
            ("HDFC", "HDFC Mutual Fund"),
            ("HSBC", "HSBC Mutual Fund"),
            ("ICICI", "ICICI Prudential Mutual Fund"),
            ("INVESCO", "Invesco Mutual Fund"),
            ("NIPPON", "Nippon India Mutual Fund"),
            ("PARAG PARIKH", "PPFAS Mutual Fund"),
            ("PPFAS", "PPFAS Mutual Fund"),
            ("SBI", "SBI Mutual Fund"),
            ("TRUST", "Trust Mutual Fund"),
            ("KOTAK", "Kotak Mahindra Mutual Fund"),
            ("AXIS", "Axis Mutual Fund"),
            ("TATA", "Tata Mutual Fund"),
            ("MIRAE", "Mirae Asset Mutual Fund"),
            ("MOTILAL", "Motilal Oswal Mutual Fund"),
            ("UTI", "UTI Mutual Fund"),
            ("DSP", "DSP Mutual Fund"),
        ]
        for key, brand in KNOWN_AMCS:
            if key in s_upper:
                return brand

        parts = scheme_name.split()
        return " ".join(parts[:2]).title() + " Mutual Fund"

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Compile complete portfolio dashboard metrics, scheme list, and charts data."""
        val_date = self.get_valuation_date()
        holders = self.portfolio_data.get('holders', [])
        client_name = holders[0].get('Holder Name') if holders else None
        if not client_name:
            m = re.match(r'Portfolio_(.+?)_\d{4}-\d{2}-\d{2}', self.excel_path.stem, re.IGNORECASE)
            client_name = m.group(1).replace('_', ' ') if m else "Valued Client"

        # Summary KPIs
        total_sip = sum(_to_float(h.get('SIP')) for h in holders)
        total_cost = sum(_to_float(h.get('Cost of Investment')) for h in holders)
        total_current = sum(_to_float(h.get('Current Value')) for h in holders)
        net_gain = total_current - total_cost
        gain_pct = (net_gain / total_cost * 100) if total_cost > 0 else 0

        # Weighted XIRR & ABS
        weighted_xirr_sum = sum(_to_float(h.get('XIRR')) * _to_float(h.get('Current Value')) for h in holders)
        avg_xirr = (weighted_xirr_sum / total_current) if total_current > 0 else 0
        abs_return = _to_float(holders[0].get('ABS')) if (holders and holders[0].get('ABS')) else gain_pct

        # Map Folio Wise details by Scheme Name
        folio_map = {}
        for h_name, sch_list in self.portfolio_data.get('portfolio_schemes', {}).items():
            for s in sch_list:
                sname = str(s.get('Scheme Name', '')).strip()
                if sname:
                    folio_map[sname] = s

        # Map Category & Fund House from Transaction Wise and AMC Wise
        tx_list = self.portfolio_data.get('transactions', [])
        tx_map = {}
        for t in tx_list:
            sname = str(t.get('Sheme Name') or t.get('Scheme Name') or '').strip()
            if sname and sname not in tx_map:
                tx_map[sname] = t

        amc_list = self.portfolio_data.get('amc_wise', [])

        # Build schemes list from Scheme Wise (or fallback to Folio Wise)
        raw_schemes = self.portfolio_data.get('scheme_wise', [])
        schemes = []

        if raw_schemes:
            for s in raw_schemes:
                name = str(s.get('Scheme Name', '')).strip()
                if not name or name.lower() == 'total':
                    continue
                cost = _to_float(s.get('Cost of Investment'))
                val = _to_float(s.get('Current Value'))
                pl = _to_float(s.get('Notional P/L') if s.get('Notional P/L') is not None else (val - cost))
                ret_pct = _to_float(s.get('ABS') if s.get('ABS') is not None else ((pl / cost * 100) if cost > 0 else 0))
                xirr_val = _to_float(s.get('XIRR'))
                weight = _to_float(s.get('Mkt Wgt') if s.get('Mkt Wgt') is not None else ((val / total_current * 100) if total_current > 0 else 0))

                t_match = tx_map.get(name, {})
                f_match = folio_map.get(name, {})

                cat = t_match.get('Sub Sector') or t_match.get('Sector') or 'Equity Mutual Fund'
                fund_house = self._detect_fund_house(name, amc_list)
                units = _to_float(f_match.get('Units') or t_match.get('Units'))
                curr_nav = _to_float(f_match.get('Current NAV'))
                avg_nav = _to_float(f_match.get('Avg NAV'))
                folio_no = str(f_match.get('Folio No') or '')
                nominee = str(f_match.get('Nominee') or '')

                schemes.append({
                    'scheme_name': name,
                    'url_name': quote(name, safe=''),
                    'category': cat,
                    'fund_house': fund_house,
                    'invested_amount': round(cost, 2),
                    'current_value': round(val, 2),
                    'gain_loss': round(pl, 2),
                    'gain_loss_pct': round(ret_pct, 2),
                    'return_pct': round(ret_pct, 2),
                    'xirr': round(xirr_val, 2),
                    'portfolio_weight': round(weight, 2),
                    'units': round(units, 3) if units else None,
                    'current_nav': round(curr_nav, 2) if curr_nav else None,
                    'avg_nav': round(avg_nav, 2) if avg_nav else None,
                    'folio_no': folio_no,
                    'nominee': nominee,
                })
        else:
            for name, f_match in folio_map.items():
                cost = _to_float(f_match.get('Cost of Investment'))
                val = _to_float(f_match.get('Current value'))
                pl = _to_float(f_match.get('Notional P/L') if f_match.get('Notional P/L') is not None else (val - cost))
                ret_pct = _to_float(f_match.get('ABS') if f_match.get('ABS') is not None else ((pl / cost * 100) if cost > 0 else 0))
                xirr_val = _to_float(f_match.get('XIRR'))
                weight = (val / total_current * 100) if total_current > 0 else 0
                t_match = tx_map.get(name, {})
                cat = t_match.get('Sub Sector') or t_match.get('Sector') or 'Equity Mutual Fund'
                fund_house = self._detect_fund_house(name, amc_list)

                schemes.append({
                    'scheme_name': name,
                    'url_name': quote(name, safe=''),
                    'category': cat,
                    'fund_house': fund_house,
                    'invested_amount': round(cost, 2),
                    'current_value': round(val, 2),
                    'gain_loss': round(pl, 2),
                    'gain_loss_pct': round(ret_pct, 2),
                    'return_pct': round(ret_pct, 2),
                    'xirr': round(xirr_val, 2),
                    'portfolio_weight': round(weight, 2),
                    'units': _to_float(f_match.get('Units')),
                    'current_nav': _to_float(f_match.get('Current NAV')),
                    'avg_nav': _to_float(f_match.get('Avg NAV')),
                    'folio_no': str(f_match.get('Folio No') or ''),
                    'nominee': str(f_match.get('Nominee') or ''),
                })

        # Chart Data
        sorted_for_charts = sorted(schemes, key=lambda x: x['current_value'], reverse=True)
        chart_data = {
            'allocation': {
                'labels': [s['scheme_name'] for s in sorted_for_charts],
                'values': [s['current_value'] for s in sorted_for_charts],
                'weights': [s['portfolio_weight'] for s in sorted_for_charts],
            },
            'comparison': {
                'labels': [s['scheme_name'] for s in sorted_for_charts],
                'invested': [s['invested_amount'] for s in sorted_for_charts],
                'current': [s['current_value'] for s in sorted_for_charts],
            }
        }

        return {
            'client_name': client_name,
            'valuation_date': val_date,
            'summary': {
                'total_invested': round(total_cost, 2),
                'current_value': round(total_current, 2),
                'total_gain_loss': round(net_gain, 2),
                'gain_loss_percentage': round(gain_pct, 2),
                'abs_return': round(abs_return, 2),
                'xirr': round(avg_xirr, 2),
                'total_sip': round(total_sip, 2),
            },
            'schemes': schemes,
            'chart_data': chart_data,
            'holders': [h.get('Holder Name') for h in holders if h.get('Holder Name')],
        }

    def get_scheme_details(self, scheme_name: str) -> Dict[str, Any]:
        """Retrieve holding summary, scheme info, transaction history, and NAV history for a scheme."""
        dash = self.get_dashboard_data()
        schemes = dash['schemes']

        target = scheme_name.strip().lower()
        matched = None
        for s in schemes:
            if s['scheme_name'].strip().lower() == target:
                matched = s
                break
        if not matched:
            for s in schemes:
                if target in s['scheme_name'].strip().lower() or s['scheme_name'].strip().lower() in target:
                    matched = s
                    break

        if not matched:
            return None

        # Transactions for this scheme
        all_txs = self.portfolio_data.get('transactions', [])
        tx_col = 'Sheme Name' if (all_txs and 'Sheme Name' in all_txs[0]) else 'Scheme Name'

        matched_txs = []
        for t in all_txs:
            tname = str(t.get(tx_col) or t.get('Scheme Name') or t.get('Sheme Name') or '').strip().lower()
            if tname == matched['scheme_name'].strip().lower() or tname == target:
                amt = _to_float(t.get('Amount'))
                units = _to_float(t.get('Units'))
                nav = _to_float(t.get('NavRate'))
                dt_str = str(t.get('Date') or '')
                tx_type = str(t.get('Transaction') or 'SIP')

                matched_txs.append({
                    'date': dt_str,
                    'amount': round(amt, 2),
                    'type': tx_type,
                    'units': round(units, 3),
                    'nav': round(nav, 2),
                })

        # Sort transactions chronologically
        def parse_date(d_str):
            try:
                return pd.to_datetime(d_str, format='%d/%m/%Y', errors='coerce')
            except Exception:
                return pd.NaT

        matched_txs.sort(key=lambda x: parse_date(x['date']) if pd.notna(parse_date(x['date'])) else pd.Timestamp.min)

        # Build NAV History points for the chart
        nav_history = []
        seen_dates = set()
        for tx in matched_txs:
            if tx['nav'] > 0 and tx['date'] and tx['date'] not in seen_dates:
                seen_dates.add(tx['date'])
                nav_history.append({
                    'date': tx['date'],
                    'nav': tx['nav'],
                })

        # Add latest NAV point if available
        if matched.get('current_nav') and matched['current_nav'] > 0:
            val_date = dash['valuation_date']
            if val_date not in seen_dates:
                nav_history.append({
                    'date': val_date,
                    'nav': matched['current_nav'],
                })

        if len(nav_history) == 1 and matched.get('avg_nav') and matched.get('current_nav'):
            if matched['avg_nav'] != matched['current_nav']:
                nav_history.insert(0, {
                    'date': 'Initial Cost NAV',
                    'nav': matched['avg_nav']
                })

        # Build Growth Timeline (Cumulative Invested Amount vs Current Value over time)
        growth_timeline = []
        if matched_txs:
            cum_invested = 0.0
            cum_units = 0.0
            for tx in matched_txs:
                cum_invested += float(tx['amount'] or 0)
                cum_units += float(tx['units'] or 0)
                nav_val = float(tx['nav'] or 0)
                growth_timeline.append({
                    'date': tx['date'],
                    'invested': round(cum_invested, 2),
                    'value': round(cum_units * nav_val, 2),
                })

            val_date = dash['valuation_date']
            if growth_timeline and growth_timeline[-1]['date'] != val_date:
                growth_timeline.append({
                    'date': val_date,
                    'invested': matched['invested_amount'],
                    'value': matched['current_value'],
                })
            elif growth_timeline:
                growth_timeline[-1]['invested'] = matched['invested_amount']
                growth_timeline[-1]['value'] = matched['current_value']
        else:
            val_date = dash['valuation_date']
            growth_timeline = [
                {
                    'date': 'Initial Investment',
                    'invested': matched['invested_amount'],
                    'value': matched['invested_amount'],
                },
                {
                    'date': val_date,
                    'invested': matched['invested_amount'],
                    'value': matched['current_value'],
                }
            ]

        return {
            'client_name': dash['client_name'],
            'valuation_date': dash['valuation_date'],
            'scheme_name': matched['scheme_name'],
            'url_name': matched['url_name'],
            'holding_summary': {
                'invested_amount': matched['invested_amount'],
                'current_value': matched['current_value'],
                'gain_loss': matched['gain_loss'],
                'gain_loss_pct': matched['gain_loss_pct'],
                'portfolio_weight': matched['portfolio_weight'],
                'return_pct': matched['return_pct'],
                'xirr': matched['xirr'],
            },
            'scheme_info': {
                'fund_house': matched['fund_house'],
                'category': matched['category'],
                'units_held': matched['units'],
                'latest_nav': matched['current_nav'],
                'avg_nav': matched['avg_nav'],
                'folio_no': matched['folio_no'],
                'nominee': matched['nominee'],
            },
            'transactions': matched_txs,
            'nav_history': nav_history,
            'growth_timeline': growth_timeline,
            'chat_prefill': f"How has my investment in {matched['scheme_name']} performed?",
        }
