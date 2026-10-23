"""Summarize evidence gaps. This command cannot issue execution approvals."""
import argparse
import json
from pathlib import Path


def build(folder):
    audit=json.loads((folder/'audit.json').read_text())
    stops=json.loads((folder/'stop-hypotheses.json').read_text())
    symbols={}
    for row in audit['symbols']:
        source=stops['symbols'].get(row['symbol'],{})
        symbols[row['symbol']]={'historical_calendar_days':source.get('calendar_days'),
            'historical_timeframe_matches_run':source.get('matches_audit_timeframe',False),
            'historical_data_independent':False,'minimum_historical_days':90,
            'forward_paper_started_after_candidate_freeze':False,'minimum_forward_paper_days':14,
            'minimum_out_of_sample_trades':100,'minimum_forward_paper_trades':100,
            'current_demo_trades_are_forward_paper_validation':False,
            'status':'insufficient_independent_evidence'}
    news={'status':'profitability_ab_not_performed','current_execution_mode':'report_only',
        'recorded_entry_scores_with_news':audit['findings']['news_adjusted_filled_entries'],
        'resolved_ranking_changes':audit['findings']['news_ranking_changes_among_resolved_entries'],
        'unresolved_ties':audit['findings']['unresolved_news_ranking_ties'],
        'caveat':'Same-time score reconstruction cannot identify the returns, sizing or later learning of an independent no-news run.',
        'needed':'Freeze a technical baseline and a news variant before new chronological testing; record the same costs and risk for both.'}
    readiness={'schema':1,'status':'not_ready_for_execution','automatic_deployment':False,
        'approved_strategies':[],'symbols':symbols,
        'remaining':['90+ days of broker history for each matching timeframe, with realistic costs.',
            'Frozen strategy definitions and chronological, independent out-of-sample results.',
            'New forward-paper observations after freezing candidates; no broker orders.',
            'Separate technical-only versus technical-plus-news comparison before enabling news execution effects.',
            'Review evidence before any execution approval; passing software tests is not profitability evidence.']}
    (folder/'readiness.json').write_text(json.dumps(readiness,indent=2))
    (folder/'news-ab.json').write_text(json.dumps(news,indent=2))
    return readiness


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,default=Path(__file__).resolve().parents[1]/'reports/trading-audit/20261022')
    result=build(parser.parse_args().folder);print(result['status'])
