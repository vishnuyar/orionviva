from viva.desktop_bridge.conversation_actions import _ask_request
import pytest


def test_explicit_anchored_recovery_is_admitted_without_changing_legacy_request_tuple():
    result=_ask_request({'question':'Continue the allocation answer','context_mode':'follow_up','continuation_recovery':{'version':'allocation-continuation-v1','turn_id':'turn-1','answer_id':'answer-1'}})
    assert result==('Continue the allocation answer',True,False,'follow_up')

@pytest.mark.parametrize('mode,anchor',[
 ('new_question',{'version':'allocation-continuation-v1','turn_id':'t','answer_id':'a'}),
 ('follow_up',{'version':'unknown','turn_id':'t','answer_id':'a'}),
 ('follow_up',{'version':'allocation-continuation-v1','turn_id':'t','answer_id':'a','account':'forged'}),
 ('follow_up',{'version':'allocation-continuation-v1','turn_id':'t'}),
 ('follow_up',{'version':'allocation-continuation-v1','turn_id':'t','answer_id':True}),
 ('follow_up',{'version':'allocation-continuation-v1','turn_id':'t','answer_id':'a'*129}),
 ('follow_up',{'version':'allocation-continuation-v1','turn_id':'t','answer_id':'雪'}),
])
def test_malformed_or_incompatible_recovery_rejected_at_real_bridge_boundary(mode,anchor):
    from viva.desktop_bridge.handlers import BridgeRequestError
    with pytest.raises(BridgeRequestError):_ask_request({'question':'Continue','context_mode':mode,'continuation_recovery':anchor})
