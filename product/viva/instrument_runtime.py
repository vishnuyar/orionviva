"""One authenticated immutable revision per executable instrument program."""
from contextlib import contextmanager,ExitStack
from time import monotonic,sleep
from .instrument_claims import ResolvedTargetPremise

class InstrumentRuntime:
    def __init__(self,supplier=None):
        self.supplier=supplier;self.revision=None;self.deadline=None;self.problem='';self.run_token=None
        self.target_premises={};self.question="";self.target_validator=None;self.started=None;self.read_count=0;self.current_question_id=""

    @contextmanager
    def execution(self,deadline,*,question=""):
        if self.revision is not None:raise ValueError('nested instrument execution')
        self.deadline=deadline;self.started=monotonic();self.problem='';self.run_token=object();self.question=question;self.read_count=0
        try:
            with ExitStack() as stack:
                try:
                    if self.supplier is None:raise ValueError('no instrument supplier')
                    scope=self.supplier(deadline=min(deadline,self.started+2)) if getattr(self.supplier,"deadline_aware",False) else self.supplier()
                    revision=stack.enter_context(scope)
                    revision._store.authenticated_source_identity(revision)
                except Exception:
                    self.problem='current authenticated instrument read is unavailable';yield self;return
                self.revision=revision
                yield self
        finally:
            self.revision=None;self.deadline=None;self.problem='';self.run_token=None;self.question="";self.started=None

    def source_is_current(self):
        check=getattr(self.supplier,"source_identity",None)
        expected=getattr(self.supplier,"expected_projection_identity",None)
        return check is None or expected is None or check()==expected

    def resolve_target(self,reference,request):
        premise=self.target_premises.get(reference)
        if type(premise) is not ResolvedTargetPremise or premise.question_id!=self.current_question_id or (premise.account,premise.currency,premise.as_of)!=(request.account,request.currency,request.as_of):
            raise ValueError('current allocation target premise is unavailable')
        if self.target_validator is None or not self.target_validator(premise,self.revision,self.question,deadline=getattr(self,"read_deadline",self.deadline)):
            raise ValueError('current allocation target dependencies changed')
        return premise


def vault_revision_supplier(vault):
    @contextmanager
    def current(*,deadline=None):
        from .read_store import ReadStoreError
        deadline=min(deadline if deadline is not None else monotonic()+2,monotonic()+2)
        if not vault.wait_for_read_store(timeout=max(0,deadline-monotonic())):
            raise ReadStoreError('current read store did not catch up within its bound')
        with vault.read_store.open_reader() as revision:
            identity=vault.read_store.authenticated_source_identity(revision)
            observed=vault.ledger.store.authenticated_identity()
            if (identity.get('count'),identity.get('head'))!=observed[:2] or monotonic()>=deadline:
                raise ReadStoreError('current instrument source changed or exceeded its bound')
            yield revision
    current.source_identity=lambda:vault.ledger.store.authenticated_identity()
    current.expected_projection_identity=getattr(getattr(vault,"ledger",None),"_projection_identity",None)
    current.deadline_aware=True
    return current
