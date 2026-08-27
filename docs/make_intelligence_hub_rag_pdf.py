import os
import sys
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT_PDF = Path(__file__).parent / "Intelligence_Hub_RAG_Architecture.pdf"
CHROMIUM_PATH = r"C:\Users\selva\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe"

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>StratRoom Intelligence Hub — RAG Model Architecture & Technical Specification</title>
<style>
  @page {
    size: A4;
    margin: 20mm 15mm 20mm 15mm;
    @bottom-center {
      content: "StratRoom Intelligence Hub — RAG System Specification";
      font-size: 8pt;
      font-family: Arial, sans-serif;
      color: #64748b;
    }
  }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1e293b;
    background-color: #ffffff;
    line-height: 1.5;
    font-size: 10pt;
    margin: 0;
    padding: 0;
  }

  /* Header Cover Style */
  .header-card {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #334155 100%);
    color: #ffffff;
    padding: 28px 32px;
    border-radius: 12px;
    margin-bottom: 28px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  }

  .header-card h1 {
    font-size: 22pt;
    font-weight: 800;
    margin: 0 0 6px 0;
    letter-spacing: -0.5px;
    color: #38bdf8;
  }

  .header-card .subtitle {
    font-size: 12pt;
    font-weight: 500;
    color: #94a3b8;
    margin: 0 0 16px 0;
  }

  .meta-tags {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }

  .tag {
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
    color: #e2e8f0;
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 8.5pt;
    font-weight: 600;
  }

  h2 {
    font-size: 13pt;
    font-weight: 700;
    color: #0f172a;
    border-bottom: 2px solid #e2e8f0;
    padding-bottom: 6px;
    margin-top: 24px;
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
    page-break-after: avoid;
  }

  h3 {
    font-size: 10.5pt;
    font-weight: 700;
    color: #1e293b;
    margin-top: 16px;
    margin-bottom: 6px;
    page-break-after: avoid;
  }

  p {
    margin-top: 0;
    margin-bottom: 10px;
    text-align: justify;
  }

  ul, ol {
    margin-top: 0;
    margin-bottom: 10px;
    padding-left: 20px;
  }

  li {
    margin-bottom: 4px;
  }

  .callout {
    background: #f8fafc;
    border-left: 4px solid #0284c7;
    padding: 12px 16px;
    border-radius: 0 8px 8px 0;
    margin: 14px 0;
    font-size: 9.5pt;
  }

  .callout-title {
    font-weight: 700;
    color: #0369a1;
    margin-bottom: 4px;
  }

  /* Tables */
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 14px 0;
    font-size: 9pt;
    page-break-inside: avoid;
  }

  th {
    background: #f1f5f9;
    color: #334155;
    font-weight: 700;
    text-align: left;
    padding: 8px 12px;
    border: 1px solid #cbd5e1;
  }

  td {
    padding: 8px 12px;
    border: 1px solid #e2e8f0;
    vertical-align: top;
  }

  tr:nth-child(even) td {
    background: #f8fafc;
  }

  code {
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace;
    font-size: 8.5pt;
    background: #f1f5f9;
    color: #0f172a;
    padding: 2px 5px;
    border-radius: 4px;
    border: 1px solid #e2e8f0;
  }

  pre {
    background: #0f172a;
    color: #f8fafc;
    padding: 14px 16px;
    border-radius: 8px;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace;
    font-size: 8.5pt;
    line-height: 1.45;
    overflow-x: auto;
    margin: 14px 0;
    page-break-inside: avoid;
  }

  pre code {
    background: transparent;
    color: inherit;
    padding: 0;
    border: none;
  }

  .badge-blue { background: #e0f2fe; color: #0369a1; }
  .badge-purple { background: #f3e8ff; color: #7e22ce; }
  .badge-green { background: #dcfce7; color: #15803d; }
  .badge-amber { background: #fef3c7; color: #b45309; }

  .status-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 700;
    font-size: 8pt;
  }

  .grid-2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin: 14px 0;
  }

  .card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 12px 14px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  }

  .card-title {
    font-weight: 700;
    font-size: 9.5pt;
    color: #0f172a;
    margin-bottom: 6px;
  }
</style>
</head>
<body>

  <!-- HEADER COVER -->
  <div class="header-card">
    <h1>StratRoom Intelligence Hub</h1>
    <div class="subtitle">Retrieval-Augmented Generation (RAG) Architecture & System Specification</div>
    <div class="meta-tags">
      <span class="tag">Scope: Enterprise Document RAG</span>
      <span class="tag">Engine: Dual-Mode Hybrid Search</span>
      <span class="tag">Security: Multi-Tenant & RBAC</span>
      <span class="tag">Status: Production Spec</span>
    </div>
  </div>

  <!-- SECTION 1 -->
  <h2>1. Executive Summary & Design Architecture</h2>
  <p>
    StratRoom’s Intelligence Hub introduces a <strong>Retrieval-Augmented Generation (RAG) Architecture</strong> designed specifically for enterprise governance, risk, compliance, and strategic decision documentation. While StratRoom's core operational system utilizes structured tool-calling for relational MySQL tables, the Intelligence Hub handles <strong>unstructured knowledge sources</strong>—including policy frameworks, board meeting decks, regulatory filings, vendor contracts, and audit reports.
  </p>

  <div class="callout">
    <div class="callout-title">Core Architectural Principle: Hybrid Intelligence</div>
    RAG operates in tandem with StratRoom's SQL Agent Runner. Structured queries (KPI values, task counts, budget lines) execute direct MySQL queries, while qualitative and semantic inquiries ("What are our SLA default penalties in Q3 contracts?") route through the Vector RAG Engine.
  </div>

  <div class="grid-2">
    <div class="card">
      <div class="card-title">🎯 Primary RAG Objectives</div>
      <ul>
        <li><strong>Zero Hallucination Grounding:</strong> Enforce strict prompt constraints limiting answers to retrieved passages.</li>
        <li><strong>Exact Provenance Citation:</strong> Provide page-level and section-level attribution for every generated claim.</li>
        <li><strong>Multi-Format Ingestion:</strong> Seamless parsing for PDF, DOCX, XLSX, and Markdown files.</li>
      </ul>
    </div>
    <div class="card">
      <div class="card-title">🔒 Enterprise Governance</div>
      <ul>
        <li><strong>Multi-Tenancy Isolation:</strong> Metadata pre-filtering guarantees strict <code>org_id</code> workspace boundaries.</li>
        <li><strong>Role-Based Access Control:</strong> Enforces document visibility levels (Executive, Manager, Member).</li>
        <li><strong>Audit Logging:</strong> Full provenance logging of queries, retrieved vector chunk IDs, and similarity scores.</li>
      </ul>
    </div>
  </div>

  <!-- SECTION 2 -->
  <h2>2. End-to-End Data Flow & Pipeline</h2>
  <p>The RAG pipeline operates across two decoupled phases: <strong>Document Ingestion & Indexing</strong> (Asynchronous) and <strong>Semantic Retrieval & Synthesis</strong> (Synchronous Execution).</p>

  <pre><code>+-----------------------------------------------------------------------------------+
|                            DOCUMENT INGESTION PIPELINE                            |
+-----------------------------------------------------------------------------------+
[ User File Upload ] ──► [ Layout & Text Extraction ] ──► [ Semantic Token Chunking ]
  (PDF / DOCX / XLSX)     (PyMuPDF / Docx / OpenPyXL)      (512 Tokens / 64 Overlap)
                                                                    │
                                                                    ▼
[ Vector Store Indexing ] ◄── [ Embedding Generation ] ◄────────────┘
  (MySQL Vector / HNSW)       (text-embedding-3-small)

+-----------------------------------------------------------------------------------+
|                        QUERY & RETRIEVAL SYNTHESIS PIPELINE                        |
+-----------------------------------------------------------------------------------+
[ User Query Input ] ──► [ Query Intent Classifier ] ──► [ Dense & Sparse Hybrid Search ]
                                                           (Vector Cosine + BM25 Keyword)
                                                                    │
                                                                    ▼
[ Grounded LLM Response ] ◄── [ Context & Citation Assembly ] ◄── [ Re-Ranking Engine ]
  (With Page Citations)         (Top-5 Context Passages)          (Cross-Encoder Score > 0.75)</code></pre>

  <!-- SECTION 3 -->
  <h2>3. Document Ingestion & Extraction Engine</h2>
  <p>The ingestion engine standardizes unstructured multi-format uploads into standardized, text-searchable chunks with rich structural metadata.</p>

  <table>
    <thead>
      <tr>
        <th>File Format</th>
        <th>Parsing Subsystem</th>
        <th>Extraction Capabilities</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><code>.pdf</code></td>
        <td>PyMuPDF (<code>fitz</code>)</td>
        <td>Extracts layout coordinates, multi-column reading flow, embedded tables, and page boundaries.</td>
      </tr>
      <tr>
        <td><code>.docx</code></td>
        <td><code>python-docx</code></td>
        <td>Parses XML DOM structure, heading hierarchies (H1/H2/H3), paragraph lists, and document properties.</td>
      </tr>
      <tr>
        <td><code>.xlsx</code></td>
        <td><code>openpyxl</code></td>
        <td>Converts tabular spreadsheet grids into Markdown table representations per worksheet tab.</td>
      </tr>
      <tr>
        <td><code>.txt / .md</code></td>
        <td>Native UTF-8 Stream</td>
        <td>Direct plaintext parsing with header boundary preservation.</td>
      </tr>
    </tbody>
  </table>

  <h3>Chunking & Tokenization Parameters</h3>
  <ul>
    <li><strong>Chunk Strategy:</strong> Semantic Recursive Character Splitter with paragraph boundary alignment.</li>
    <li><strong>Chunk Target Size:</strong> 512 tokens (~2,000 characters).</li>
    <li><strong>Chunk Overlap:</strong> 64 tokens (~250 characters) to preserve contextual continuity across chunk boundaries.</li>
    <li><strong>Metadata Enriched Attributes:</strong> <code>document_id</code>, <code>org_id</code>, <code>user_id</code>, <code>page_number</code>, <code>section_title</code>, <code>chunk_index</code>, <code>access_role</code>.</li>
  </ul>

  <!-- SECTION 4 -->
  <h2>4. Embedding Generation & Vector Storage Schema</h2>
  <p>Document chunks are converted into high-dimensional dense vector embeddings and indexed for low-latency similarity queries.</p>

  <div class="grid-2">
    <div class="card">
      <div class="card-title">⚡ Embedding Configuration</div>
      <ul>
        <li><strong>Primary Model:</strong> OpenAI <code>text-embedding-3-small</code></li>
        <li><strong>Vector Dimensions:</strong> 1,536 dimensions</li>
        <li><strong>Distance Metric:</strong> Cosine Distance (L2 Normalized)</li>
        <li><strong>Fallback Model:</strong> <code>bge-small-en-v1.5</code> (384 dimensions)</li>
      </ul>
    </div>
    <div class="card">
      <div class="card-title">🗄️ Indexing Strategy</div>
      <ul>
        <li><strong>Index Type:</strong> HNSW (Hierarchical Navigable Small World)</li>
        <li><strong>M Parameter:</strong> 16 connections per node</li>
        <li><strong>efConstruction:</strong> 200 candidate evaluation depth</li>
        <li><strong>Query Latency Target:</strong> &lt; 15 milliseconds</li>
      </ul>
    </div>
  </div>

  <h3>MySQL Database Schema (<code>document_embeddings</code>)</h3>
  <pre><code>CREATE TABLE document_embeddings (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    document_id BIGINT NOT NULL,
    org_id INT NOT NULL,
    user_id INT NOT NULL,
    chunk_index INT NOT NULL,
    page_number INT NOT NULL,
    section_title VARCHAR(255) NULL,
    chunk_text MEDIUMTEXT NOT NULL,
    token_count INT NOT NULL,
    embedding VECTOR(1536) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_org_doc (org_id, document_id),
    VECTOR INDEX idx_embedding (embedding) USING HNSW
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;</code></pre>

  <!-- SECTION 5 -->
  <h2>5. Hybrid Retrieval & Re-Ranking Strategy</h2>
  <p>To maximize recall accuracy for specialized terminology while preserving semantic search for natural language queries, the system employs a <strong>Hybrid Search & Re-Ranking Pipeline</strong>.</p>

  <table>
    <thead>
      <tr>
        <th>Retrieval Mode</th>
        <th>Algorithm / Index</th>
        <th>Primary Purpose</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>Sparse Search</strong></td>
        <td>SQL Full-Text (BM25)</td>
        <td>Matches exact key phrases, clause numbers, regulation codes (e.g. "ISO-27001 Section 4.2").</td>
      </tr>
      <tr>
        <td><strong>Dense Search</strong></td>
        <td>Cosine Vector Distance</td>
        <td>Captures semantic concepts, synonyms, and intent ("data security requirements").</td>
      </tr>
      <tr>
        <td><strong>Score Fusion</strong></td>
        <td>Reciprocal Rank Fusion (RRF)</td>
        <td>Combines sparse and dense ranks: <code>RRF_Score(d) = Σ 1 / (60 + Rank(d))</code>.</td>
      </tr>
      <tr>
        <td><strong>Re-Ranker</strong></td>
        <td>Cross-Encoder (<code>bge-reranker-large</code>)</td>
        <td>Evaluates Top-20 candidate passages against the query, filtering candidates below 0.75 score.</td>
      </tr>
    </tbody>
  </table>

  <!-- SECTION 6 -->
  <h2>6. Context Assembly & Grounded Prompt Enforcement</h2>
  <p>The top 5 re-ranked document passages are formatted into a structured context block injected into the LLM system prompt.</p>

  <pre><code>SYSTEM PROMPT GUARDRAILS:
You are StratRoom AI Intelligence Hub assistant. Answer the user's inquiry strictly using
the retrieved context passages below.

RULES:
1. Base your answer ONLY on the provided context passages. Do not invent or assume facts.
2. For every assertion or data point, provide an inline citation in the format [Doc: File_Name, Page X].
3. If the context does not contain sufficient details to answer, state: "The uploaded documents do not contain information regarding [topic]."

CONTEXT PASSAGES:
[Passage 1 | Doc: Executive_Risk_Report.pdf | Page 4]
The cybersecurity risk index increased by 14% due to delayed patch cycles in legacy servers...

[Passage 2 | Doc: Compliance_Audit.pdf | Page 12]
Section 3.1 requires mandatory multi-factor authentication across all external access portals...</code></pre>

  <!-- SECTION 7 -->
  <h2>7. Multi-Tenancy Isolation & Security Control</h2>
  <ul>
    <li><strong>Pre-Retrieval Metadata Filtering:</strong> Vector distance calculations execute <em>after</em> strict SQL filtering on <code>org_id = :current_user_org_id</code>, ensuring absolute isolation between enterprise tenants.</li>
    <li><strong>Role-Based Access Control (RBAC):</strong> Documents tagged as <code>executive</code> visibility are excluded from vector queries initiated by <code>member</code> role tokens.</li>
    <li><strong>Path Traversal & Execution Guardrails:</strong> File storage operations enforce realpath canonicalization using <code>os.path.realpath()</code> against the root storage directory.</li>
  </ul>

  <!-- SECTION 8 -->
  <h2>8. Performance Optimization & Cache Architecture</h2>
  <div class="grid-2">
    <div class="card">
      <div class="card-title">🚀 Latency Optimization</div>
      <ul>
        <li><strong>Embedding Deduplication:</strong> MD5 hashing on chunk content prevents re-embedding identical text passages.</li>
        <li><strong>Asynchronous Background Chunking:</strong> Upload endpoint returns document handle instantly; chunking executes asynchronously.</li>
      </ul>
    </div>
    <div class="card">
      <div class="card-title">💡 Context Compression</div>
      <ul>
        <li><strong>Dynamic Context Window:</strong> Automatically trims context passages if total prompt length exceeds 4,000 tokens.</li>
        <li><strong>Semantic Deduplication:</strong> Removes near-duplicate passages with Cosine similarity &gt; 0.92.</li>
      </ul>
    </div>
  </div>

</body>
</html>
"""

def generate_pdf():
    print(f"Generating PDF spec -> {OUT_PDF}")
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".html", encoding="utf-8") as f:
        f.write(HTML_CONTENT)
        html_path = f.name

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROMIUM_PATH)
            page = browser.new_page()
            page.goto(Path(html_path).as_uri())
            page.pdf(
                path=str(OUT_PDF),
                format="A4",
                print_background=True,
                margin={"top": "15mm", "bottom": "15mm", "left": "15mm", "right": "15mm"}
            )
            browser.close()
        print("[SUCCESS] PDF successfully generated!")
    finally:
        if os.path.exists(html_path):
            os.remove(html_path)

if __name__ == "__main__":
    generate_pdf()
