# Retrieval-augmented generation

Retrieval combines PostgreSQL full-text ranking, pgvector similarity, structured filters, and optional reranking. Filters include subject, topic, organ, court, period, jurisdiction, document type, validity, exam, phase, area, and approval status.

Legislation chunks preserve book, title, chapter, section, subsection, article, caput, paragraph, item, letter, and sub-item identifiers. Case-law chunks preserve process, organ, rapporteur, decision/publication dates, headnote, thesis, reasoning, and disposition when available. Every chunk points to an immutable source-document version.

Two explicit modes exist: law at the exam reference date and current approved law. Historical official answer keys are never rewritten retrospectively.

Assistant responses expose answer, basis, source, organ, date, temporal mode, and confidence. Insufficient evidence produces an uncertainty statement rather than a fabricated citation.

