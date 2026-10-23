"""Check quoted evidence and downgrade unsupported short-term news predictions.

Verbatim grounding does not prove an economic inference. A separate skeptical
model pass is recorded as model review, never as independent fact verification.
"""
import re


def normalized(text):
    return re.sub(r'\s+',' ',text).strip()


def neutral(row,reason):
    return {**row,'direction':0,'confidence':min(row.get('confidence',0),.4),
            'grounding_status':reason,'execution_eligible':False}


def ground(row,evidence):
    result={**row,'proposed_direction':row['direction'],'execution_eligible':False}
    if row['direction']==0:return {**result,'grounding_status':'no_directional_claim','verified_quotes':[]}
    claims=row.get('claims');known={e['id']:e for e in evidence}
    if not isinstance(claims,list) or not 1<=len(claims)<=6:
        return neutral(result,'missing_grounded_claims')
    verified=[]
    for claim in claims:
        if not isinstance(claim,dict):return neutral(result,'invalid_claim')
        ident,quote,fact=claim.get('evidence_id'),claim.get('quote'),claim.get('fact')
        if (not isinstance(ident,str) or ident not in row['evidence_ids'] or ident not in known
                or not isinstance(quote,str) or not 20<=len(quote)<=350
                or not isinstance(fact,str) or not 5<=len(fact)<=700):
            return neutral(result,'invalid_claim')
        article=known[ident].get('article',{})
        text=article.get('text','') if article.get('status')=='read' else ''
        if not text or normalized(quote) not in normalized(text):
            return neutral(result,'quote_not_found_in_read_article')
        verified.append({'evidence_id':ident,'quote':quote,'fact':fact})
    result['verified_quotes']=verified
    if row.get('relevance')!='direct' or row.get('horizon')!='short_term':
        return neutral(result,'no_direct_short_term_support')
    return {**result,'grounding_status':'quotes_checked_awaiting_model_review'}


def review(rows,verdicts):
    if not isinstance(verdicts,dict):verdicts={}
    output={}
    for symbol,row in rows.items():
        if row['direction']==0:
            output[symbol]=row;continue
        verdict=verdicts.get(symbol,{})
        if (not isinstance(verdict,dict) or verdict.get('supported') is not True
                or verdict.get('relevance')!='direct' or verdict.get('horizon')!='short_term'
                or not isinstance(verdict.get('reason'),str) or not verdict['reason'].strip()):
            output[symbol]={**neutral(row,'skeptical_review_not_supported'),
                            'model_review':verdict if isinstance(verdict,dict) else {}}
        else:
            output[symbol]={**row,'grounding_status':'quotes_checked_model_review_supported',
                            'model_review':{'supported':True,'reason':verdict['reason'][:700]},
                            'independently_fact_verified':False}
    return output
