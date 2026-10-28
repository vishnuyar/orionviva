"""Documents-specific tagged read; legacy composition is a separate route."""
import time
from .handlers import BridgeRequestError
from ..read_store.documents_page import CONTRACT,DocumentsPageError,documents_page,parameters


def validate_documents_parameters(value):
    try:return parameters(dict(value))
    except DocumentsPageError as error:raise BridgeRequestError(error.reason) from None


def read_documents_page(vault,secret,request,*,session_scope):
    from ..env import locale_from_env
    from ..ingest.reader import live_reading_configured
    started=time.monotonic()
    vault.poll_read_store_worker()
    store=vault.read_store
    if store is None or vault.read_store_lifecycle not in {'equal','rebuilt','caught_up'}:
        return failure('revision_unavailable')
    try:
        with store.open_reader() as revision:
            from ..surface.documents_page import compose_documents_page
            data = documents_page(revision,raw=vault.raw,secret=secret,parameters_value=request,session_scope=session_scope,started=started)
            result = compose_documents_page(data,locale=locale_from_env(),reading_configured=live_reading_configured(),started=started)
            if revision._store.authenticated_source_identity(revision) != {k:v for k,v in data['revision'].items() if k != 'generation'}:
                raise DocumentsPageError('stale_cursor')
            from ..ingest.pipeline_models import (retained_source_identity,
                retained_confirmation_owner, RETAINED_READING_VERSION)
            result['retained_reading_version']=RETAINED_READING_VERSION
            selected=result['selected_document']
            if selected['state']=='ready':
                item=selected['document']; retry=item.get('retry')
                if retry and retry['state']=='available':
                    if not live_reading_configured():
                        retry.update(state='unavailable',reason='no_model')
                    else:
                        try:
                            source=retained_source_identity(data['revision'])
                            live=retained_source_identity(vault.ledger.store.authenticated_identity())
                            if source!=live:raise DocumentsPageError('stale_cursor')
                            from ..read_store.document_index import retry_capture_identity
                            commitment=retry_capture_identity(revision.connection,item['id'])
                            retry['confirmation_token']=retained_confirmation_owner(vault,create=True).issue(item['id'],commitment,source)
                        except DocumentsPageError:raise
                        except Exception:
                            retry.update(state='unavailable',reason='confirmation_unavailable',confirmation_token=None)
            if time.monotonic()-started>2.0:raise DocumentsPageError('resource_limit')
            if len(__import__('json').dumps(result,separators=(',',':'),ensure_ascii=True).encode())>100000:
                raise DocumentsPageError('resource_limit')
            return result
    except DocumentsPageError as error:return failure(error.reason)
    except Exception:return failure('revision_unavailable')


def failure(reason):
    return {'contract_version':CONTRACT,'state':'failed','reason':reason,'revision':None,
        'documents':[],'selected_document':{'state':'unavailable','reason':reason,'document':None},
        'page':{'total_documents':None,'total_unavailable_reason':reason,'page_start':0,'page_end':0,
                'page_count':0,'has_more':False,'next_cursor':None},
        'summary':{'scope':'revision','counts':None,'unavailable_reason':reason},'reading_sentence':''}
