# Local saved-original previews

Select a unique document in Statements and choose **View saved original**.
Opening document metadata or following an evidence link does not fetch its
contents. The preview is local and does not invoke a model or change the saved
original, ledger, financial interpretation or verification grade.

The viewer supports individual PDF pages, normalized PNG/JPEG images and strict
UTF-8 text. It displays a local rendition, rather than exporting the original.
PDF text is offered separately when available; raster images may have no text
alternative. Previous/Next page, keyboard controls, zoom and Close original are
available. The reading area occupies the full library width. Fit-width 100%,
200% and 400% zoom scale the same saved page rendition with local panning; they
do not fetch a higher-resolution page. Original source-region highlighting is
not implemented.

Viewing requires an opened vault, a captured content-addressed document and
matching authenticated original bytes. The handler accepts only an original ID
and page number. Files, parser output and UI payloads have fixed bounds. The
parser receives original bytes through anonymous pipes, without vault keys,
provider configuration or a file path. It runs as a disposable process with a
wall deadline; this is not an OS/network sandbox or a guarantee of total process
memory isolation. Image normalization removes inherited metadata. Text is plain
UTF-8 rendered through React text nodes, never active HTML.

| Bound | Current maximum |
| --- | --- |
| Original plaintext | 8 MiB |
| Encrypted envelope | 12 MiB |
| PDF page count | 200; only the requested page renders |
| Raster size | 2000-pixel edge, 4 million pixels |
| Normalized PNG | 1 MiB |
| Plain text/text alternative | 256 KiB |
| Serialized response | 1.5 MiB |
| Parser wall time | 10 seconds |

Unsupported types/encoding, password-protected PDFs, damaged/unverifiable bytes,
unavailable pages, exceeded bounds or a missing renderer produce a fixed
refusal. A refusal leaves the original saved. Local preview is deliberately
separate from **Read saved original again**, which may use a configured provider.

Only the current page is retained by the viewer. Closing, changing the selected
document, navigating away, ending access or beginning a vault transition clears
it and invalidates late replies. Content is not stored in browser persistence,
logs or a plaintext file cache. This does not promise JavaScript memory erasure
or prevent the OS, screenshots or the user from recording visible content.

The current secure raw-read and worker-pipe implementation uses POSIX facilities.
Windows preview is explicitly unavailable until a secure portable implementation
and Windows execution evidence exist; the declared Windows release gate remains
open. Source and packaged checks on another platform do not close it.

Actual production-browser page/source correspondence, narrow-screen legibility,
packaged parser dispatch and installed accessibility require their own evidence.
Native dialogs must be tested in a disposable OS login/VM because an isolated
HOME does not isolate the login's remembered-vault Keychain entry. Signed
clean-machine installation and unassisted-user trials remain separate gates.
