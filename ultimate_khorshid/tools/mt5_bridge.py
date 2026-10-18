"""Read-only demo MT5 bridge. No Wine Python, sockets, credentials or order API."""
import argparse
import json
import math
import os
from pathlib import Path
import time

from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec


def snapshot_path():
    configured = os.environ.get('KHORSHID_MT5_DATA_DIR')
    root = Path(configured).expanduser() if configured else Path.home() / '.mt5/drive_c/Program Files/MetaTrader 5'
    return root / 'MQL5/Files/khorshid_monitor.json'


def read_snapshot(path=None, now=None):
    path = Path(path) if path is not None else snapshot_path()
    now = time.time() if now is None else now
    try:
        with path.open('r', encoding='utf-8-sig') as stream:
            stat = os.fstat(stream.fileno())
            if stat.st_size > 1_000_000:
                raise ValueError('Snapshot exceeds size limit')
            age = now - stat.st_mtime
            if age < -5 or age > 15:
                raise ValueError('داده قدیمی است؛ متاتریدر و KhorshidMonitor باید باز و فعال باشند.')
            data = json.loads(stream.read(1_000_001))
    except FileNotFoundError:
        raise ValueError('فایل اتصال پیدا نشد. KhorshidMonitor را روی یک چارت متاتریدر اجرا کن: ' + str(path)) from None
    if not isinstance(data, dict) or data.get('schema') != 1 or data.get('read_only') is not True:
        raise ValueError('Unsupported MT5 monitor snapshot')
    if data.get('demo') is not True:
        raise ValueError('این اتصال فقط حساب دمو را می‌پذیرد؛ حساب فعلی دمو نیست یا هنوز وارد نشده‌ای.')
    if data.get('connected') is not True:
        raise ValueError('متاتریدر به سرور کارگزار وصل نیست.')
    generated = data.get('generated_utc')
    if not isinstance(generated, (int, float)) or not math.isfinite(generated) or not -5 <= now-generated <= 15:
        raise ValueError('زمان snapshot معتبر یا تازه نیست؛ ساعت سیستم و اجرای واسط را بررسی کن.')
    for name, cls in [('account', dict), ('quotes', list), ('closed_candles', list)]:
        if not isinstance(data.get(name), cls):
            raise ValueError('Incomplete MT5 snapshot: ' + name)
    data['snapshot_age_seconds'] = round(max(age, now-generated, 0), 1)
    data['note'] = 'Read only. Quote and candle times are broker time. A fresh snapshot does not mean a fresh market quote; check broker_time. No orders can be sent by this tool.'
    return data


@ToolRegistry.register('mt5_read')
class MT5ReadTool(BaseTool):
    tool_id = 'mt5_read'

    @property
    def spec(self):
        return ToolSpec(name=self.tool_id, category='mt5',
            description='خواندن واقعی وضعیت اتصال و موجودی حساب دمو متاتریدر، قیمت‌های Market Watch یا صد کندل بسته‌شده چارت. فقط خواندنی؛ معامله یا آموزش خودکار انجام نمی‌دهد. زمان قیمت را بررسی کن.',
            parameters={'type':'object', 'properties':{
                'action':{'type':'string','enum':['status','quotes','candles']},
                'symbol':{'type':'string','description':'نام دقیق نماد کارگزار؛ اختیاری. کندل فقط برای چارت دارای واسط موجود است.'}}})

    def execute(self, **params):
        try:
            action = params.get('action', 'status')
            symbol = str(params.get('symbol', '')).strip()
            if action not in ('status', 'quotes', 'candles'):
                raise ValueError('action must be status, quotes or candles')
            data = read_snapshot()
            output = {k:v for k,v in data.items() if k not in ('quotes','closed_candles')}
            if action == 'quotes':
                rows = [q for q in data['quotes'] if not symbol or q['symbol'].casefold() == symbol.casefold()]
                if not rows: raise ValueError('نماد پیدا نشد؛ نام دقیق نماد را از Market Watch بگیر.')
                output['quotes'] = rows
            if action == 'candles':
                if symbol and symbol.casefold() != data.get('chart_symbol','').casefold():
                    raise ValueError('برای کندل این نماد، چارت دارای KhorshidMonitor را به همان نماد تغییر بده.')
                if not data['closed_candles']: raise ValueError('کندل‌ها هنوز بارگذاری نشده‌اند؛ چارت را باز نگه دار و دوباره امتحان کن.')
                output['closed_candles'] = data['closed_candles']
            return ToolResult(tool_name=self.tool_id, content=json.dumps(output, ensure_ascii=False), metadata=output)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return ToolResult(tool_name=self.tool_id, content=str(exc), success=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', nargs='?', default='status', choices=['status','quotes','candles'])
    p.add_argument('--symbol', default='')
    args = p.parse_args()
    result = MT5ReadTool().execute(action=args.action, symbol=args.symbol)
    print(result.content)
    return 0 if result.success else 1

if __name__ == '__main__':
    raise SystemExit(main())
