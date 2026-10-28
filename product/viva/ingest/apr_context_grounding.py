"""Bounded measured source grammar for literal APR context, never legal meaning."""
from dataclasses import dataclass
from hashlib import sha256
import math
import re
from time import monotonic
from .apr_context_contracts import AprContextResult,GroundingReceipt,GroundedSpan,APR_FIELD_LABELS
from .instrument_contracts import Source
from .instrument_parser import decode
from .instrument_contracts import Rate

LABELS=APR_FIELD_LABELS
_HEADER=re.compile(r'Document ([^|\r\n]+) \| Account reference ([^|\r\n]+) \| ([A-Z]{3}) \| ([A-Za-z]{2}-[A-Za-z]{2})')
_LAYOUT=re.compile(r'[ \t\r\n]+')


class GroundingError(ValueError):
    pass


@dataclass(frozen=True)
class MeasuredSpan:
    span_id: int
    start: int
    end: int
    text: str
    box: tuple[float,float,float,float]
    character_boxes: tuple[tuple[float,...],...] = ()

    def __post_init__(self):
        if (type(self.span_id) is not int or not 0<=self.span_id<512 or type(self.start) is not int
                or type(self.end) is not int or not 0<=self.start<self.end<=32768
                or type(self.text) is not str or not self.text or len(self.text.encode())>4096
                or type(self.box) is not tuple or len(self.box)!=4
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in self.box)
                or self.box[0]>=self.box[2] or self.box[1]>=self.box[3]):
            raise GroundingError('unsupported_representation')
        if self.character_boxes and (type(self.character_boxes) is not tuple or len(self.character_boxes)!=len(self.text)
                or any(type(box) is not tuple or len(box)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in box) for box in self.character_boxes)):
            raise GroundingError('unsupported_representation')


@dataclass(frozen=True)
class MeasuredPage:
    document_id: str
    page: int
    text: str
    spans: tuple[MeasuredSpan,...]
    digest: str

    def __post_init__(self):
        if type(self.page) is not int or self.page<1 or type(self.text) is not str or len(self.text)>32768 or len(self.text.encode())>32768:
            raise GroundingError('source_limit')
        if type(self.spans) is not tuple or not 1<=len(self.spans)<=512 or any(type(s) is not MeasuredSpan for s in self.spans):
            raise GroundingError('source_limit')
        if self.digest!=sha256(self.text.encode()).hexdigest() or len({s.span_id for s in self.spans})!=len(self.spans):
            raise GroundingError('literal_mismatch')
        previous=-1
        for span in self.spans:
            if span.start<previous or self.text[span.start:span.end]!=span.text:
                raise GroundingError('unsupported_representation')
            previous=span.end


def _clock(deadline):
    if monotonic()>deadline:
        raise GroundingError('source_limit')


def extract_measured_page(pdf_bytes,document_id,page,*,deadline):
    """Count before extraction, inspect only the selected page and close handles."""
    deadline=min(deadline,monotonic()+0.5)
    if type(pdf_bytes) is not bytes or len(pdf_bytes)>50*1024*1024:
        raise GroundingError('source_limit')
    if type(page) is not int or not 1<=page<=200:
        raise GroundingError('invalid_context')
    import pypdfium2 as pdfium
    _clock(deadline)
    pdf=pdfium.PdfDocument(pdf_bytes)
    try:
        if len(pdf)>200:raise GroundingError('source_limit')
        if page>len(pdf):raise GroundingError('invalid_context')
        sheet=pdf[page-1]
        try:
            textpage=sheet.get_textpage()
            try:
                counter=getattr(textpage,'count_chars',None)
                if not callable(counter):raise GroundingError('unsupported_representation')
                count=counter()
                if type(count) is not int or not 0<count<=32768:raise GroundingError('source_limit')
                _clock(deadline)
                chars=[];boxes=[]
                for index in range(count):
                    if index%64==0:_clock(deadline)
                    character=textpage.get_text_range(index,1)
                    # The supported representation requires one Unicode scalar
                    # for each measured PDF text character.
                    if len(character)!=1:raise GroundingError('unsupported_representation')
                    chars.append(character)
                    boxes.append(tuple(textpage.get_charbox(index)))
                text=''.join(chars)
                if len(text.encode())>32768:raise GroundingError('source_limit')
                spans=[]
                for match in re.finditer(r'[^\r\n]+',text):
                    if not match.group().strip():continue
                    if len(spans)>=512:raise GroundingError('source_limit')
                    geometries=[boxes[i] for i in range(match.start(),match.end()) if not text[i].isspace()]
                    if not geometries:continue
                    box=(min(v[0] for v in geometries),min(v[1] for v in geometries),max(v[2] for v in geometries),max(v[3] for v in geometries))
                    spans.append(MeasuredSpan(len(spans),match.start(),match.end(),match.group(),box,tuple(boxes[match.start():match.end()])))
                _clock(deadline)
                return MeasuredPage(document_id,page,text,tuple(spans),sha256(text.encode()).hexdigest())
            finally:textpage.close()
        finally:sheet.close()
    finally:pdf.close()


def _normalize(value):
    return _LAYOUT.sub(' ',value).strip(' \t\r\n')


def _value_left(span):
    index=span.text.find(':')+1
    while index<len(span.text) and span.text[index] in ' \t':index+=1
    if not span.character_boxes or index>=len(span.character_boxes):
        raise GroundingError('unsupported_representation')
    return span.character_boxes[index][0]


def _line_geometry(span):
    if not span.character_boxes:return
    glyphs=[box for char,box in zip(span.text,span.character_boxes) if not char.isspace()]
    for first,second in zip(glyphs,glyphs[1:]):
        height=max(first[3]-first[1],second[3]-second[1])
        if height<=0 or second[0]<first[0] or second[0]-first[2]>height*4:
            raise GroundingError('unsupported_representation')


def ground_context(page,proposal,*,account_reference,currency,locale,numeric_apr,numeric_source,deadline):
    """Prove one literal occupies one field of the exact identity-bound record."""
    try:
        return _ground(page,proposal,account_reference,currency,locale,numeric_apr,numeric_source,min(deadline,monotonic()+0.5))
    except GroundingError as error:
        return AprContextResult('unavailable',reason=str(error))


def _ground(page,proposal,account_reference,currency,locale,numeric_apr,numeric_source,deadline):
    _clock(deadline)
    if type(page) is not MeasuredPage or proposal.page!=page.page:
        raise GroundingError('invalid_context')
    if numeric_source is None or numeric_source.doc_id!=page.document_id or numeric_source.page!=page.page:
        raise GroundingError('ambiguous_association')
    spans=page.spans
    headers=[]
    for index,span in enumerate(spans):
        match=_HEADER.fullmatch(span.text.strip(' \t'))
        if match:
            headers.append((index,match))
    matching=[(index,m) for index,m in headers if m[2]==account_reference and m[3]==currency and m[4]==locale]
    if len(matching)!=1 or len(headers)!=1:
        raise GroundingError('ambiguous_association')
    begin,header=matching[0]
    block=[spans[begin]]
    rows={};current=None
    for span in spans[begin+1:]:
        _clock(deadline)
        previous=block[-1]
        if span.box[3]>previous.box[1] or span.box[0]<block[0].box[0]-3:
            raise GroundingError('unsupported_representation')
        # Blank vertical section gaps terminate rather than attach footnotes.
        height=max(previous.box[3]-previous.box[1],span.box[3]-span.box[1])
        if previous.box[1]-span.box[3]>height*2.5:break
        row_match=re.fullmatch(r'([^:\r\n]+):[ \t]*(.*)',span.text)
        if row_match:
            if abs(span.box[0]-block[0].box[0])>3:
                raise GroundingError('unsupported_representation')
            label=row_match[1].strip(' \t')
            if label in rows:raise GroundingError('ambiguous_association')
            rows[label]=[span,row_match[2],[]]
            current=label
        elif current is not None:
            if abs(span.box[0]-block[0].box[0])<=3:break
            if ':' in span.text or len(rows[current][2])>=8 or abs(span.box[0]-_value_left(rows[current][0]))>3:
                raise GroundingError('unsupported_representation')
            rows[current][2].append(span)
        elif not rows and len(block)<=8:
            # Bounded introductory lines belong to the same contiguous record.
            pass
        else:
            break
        _line_geometry(span)
        block.append(span)
        if len(block)>256 or sum(len(s.text.encode()) for s in block)>8192:
            raise GroundingError('source_limit')
    label=LABELS[proposal.field]
    selected=rows.get(label)
    if selected is None:raise GroundingError('not_printed')
    line,value,continuations=selected
    selected_ids=(line.span_id,)+tuple(s.span_id for s in continuations)
    if proposal.label_span!=line.span_id or proposal.value_spans!=selected_ids:
        raise GroundingError('literal_mismatch')
    numeric=rows.get('Disclosure apr')
    if numeric_apr is not None:
        if numeric is None:raise GroundingError('ambiguous_association')
        if numeric[2]:raise GroundingError('unsupported_representation')
        try:
            rate=decode({'raw':numeric[1],'page':page.page},Rate,doc_id=page.document_id,locale=locale,currency=currency)
        except ValueError:raise GroundingError('ambiguous_association') from None
        if rate.percent!=numeric_apr:raise GroundingError('ambiguous_association')
    elif numeric is not None or 'Disclosure apr status' not in rows:
        raise GroundingError('ambiguous_association')
    retained=value+''.join('\n'+span.text for span in continuations)
    if not retained or len(retained.encode())>(256 if proposal.field=='status' else 2048):
        raise GroundingError('source_limit')
    if _normalize(retained)!=_normalize(proposal.value):raise GroundingError('literal_mismatch')
    _clock(deadline)
    receipt=GroundingReceipt('apr-labelled-record-v1',page.digest,spans[begin].span_id,
        numeric[0].span_id if numeric else None,line.span_id,selected_ids,tuple(s.span_id for s in block),
        document_id=page.document_id,page=page.page,measured_spans=tuple(GroundedSpan(s.span_id,s.start,s.end,tuple(repr(float(v)) for v in s.box),s.text) for s in block))
    return AprContextResult('accepted',retained,Source(page.document_id,page.page),receipt)


def construct_context(page,field,*,account_reference,currency,locale,numeric_apr,numeric_source,numeric_terms_observation_id,deadline):
    """Construct a candidate solely from locally measured exact-format fields."""
    from .apr_context_parser import LocalAprCandidate
    from dataclasses import replace
    try:
        _clock(deadline)
        if field not in LABELS:raise GroundingError('invalid_context')
        # Candidate construction grants no authority: the full record, numeric
        # association and geometry are independently checked by the grounder.
        matching=[]
        for index,span in enumerate(page.spans):
            match=re.fullmatch(re.escape(LABELS[field])+r':[ \t]*(.*)',span.text)
            if match:matching.append((index,span,match[1]))
        if not matching:raise GroundingError('not_printed')
        if len(matching)!=1:raise GroundingError('ambiguous_association')
        index,span,value=matching[0]
        ids=[span.span_id]
        for following in page.spans[index+1:]:
            if ':' in following.text or _HEADER.fullmatch(following.text.strip(' \t')):break
            if abs(following.box[0]-page.spans[0].box[0])<=3:break
            if abs(following.box[0]-span.box[0])<=3:break
            if abs(following.box[0]-_value_left(span))>3:raise GroundingError('unsupported_representation')
            value+='\n'+following.text;ids.append(following.span_id)
            if len(ids)>9:raise GroundingError('source_limit')
        candidate=LocalAprCandidate(field,value,page.page,span.span_id,tuple(ids))
        result=ground_context(page,candidate,account_reference=account_reference,currency=currency,locale=locale,
            numeric_apr=numeric_apr,numeric_source=numeric_source,deadline=deadline)
        if result.disposition=='accepted':
            result=replace(result,grounding=replace(result.grounding,numeric_terms_observation_id=numeric_terms_observation_id))
        return result
    except (GroundingError,ValueError) as error:
        reason=str(error) if str(error) in {'not_printed','invalid_context','source_limit','unsupported_representation','ambiguous_association','literal_mismatch'} else 'invalid_context'
        return AprContextResult('unavailable',reason=reason)
