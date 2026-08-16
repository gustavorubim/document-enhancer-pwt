# Draft-first evaluation fixtures

The checked-in text fixtures cover Markdown and plain text inputs. The evaluation script creates
the DOCX and PDF fixtures from fixed XML/PDF bytes in a temporary directory so their source
contents are deterministic without committing generated binary archives. The DOCX contains one
native table and one embedded PNG that is sent to the deterministic multimodal fake as an
image-table candidate.
