async function exportProposalMarkdown() {
  if (!proposalState.activeProposalId) return;
  try {
    const res = await api(`/api/proposals/${proposalState.activeProposalId}/export`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    const blob = new Blob([data.markdown], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = data.filename || 'proposal.md'; a.click();
    URL.revokeObjectURL(url);
  } catch (err) { alert("Export failed: " + err.message); }
}

function renderProposalToHtml(markdown) {
  if (!markdown) return '';
  let parsed = '';
  try {
    parsed = typeof marked !== 'undefined' ? marked.parse(markdown, { breaks: true, gfm: true }) : markdown;
  } catch {
    parsed = escHtml(markdown).replace(/\n/g, '<br>');
  }

  const container = document.createElement('div');
  container.innerHTML = parsed;

  // 1. Wrap all tables with a container and enhance structure
  // Collect tables first (static array) since DOM changes during iteration
  const tables = Array.from(container.querySelectorAll('table'));
  tables.forEach(table => {
    // Skip tables already processed
    if (table.classList.contains('pdf-table')) return;
    table.classList.add('pdf-table');

    // Ensure thead/tbody: move first row to thead if needed
    const firstRow = table.querySelector('tr');
    if (firstRow && !table.querySelector('thead')) {
      // Convert first row cells to th if they're td
      Array.from(firstRow.children).forEach(cell => {
        if (cell.tagName === 'TD') {
          const th = document.createElement('th');
          th.innerHTML = cell.innerHTML;
          if (cell.className) th.className = cell.className;
          firstRow.replaceChild(th, cell);
        }
      });
      const thead = document.createElement('thead');
      thead.appendChild(firstRow);  // removes firstRow from table body
      table.prepend(thead);  // safe: prepends to table
    }

    // Wrap remaining rows in tbody
    if (!table.querySelector('tbody')) {
      const tbody = document.createElement('tbody');
      const rows = Array.from(table.querySelectorAll('tr'));
      rows.forEach(r => tbody.appendChild(r));
      table.appendChild(tbody);
    }

    // Wrap table in div for overflow control
    const wrapper = document.createElement('div');
    wrapper.className = 'pdf-table-wrapper';
    if (table.parentNode) {
      table.parentNode.replaceChild(wrapper, table);
    }
    wrapper.appendChild(table);

    // Post-process: total rows, risk badges, numeric alignment
    const allRows = Array.from(table.querySelectorAll('tr'));
    allRows.forEach(tr => {
      const cells = Array.from(tr.children);
      cells.forEach(cell => {
        const txt = cell.textContent.trim();
        if (/total|grand total|toplam/i.test(txt)) {
          tr.classList.add('total-row');
        }
        if (/^(high|yüksek)$/i.test(txt)) {
          cell.innerHTML = `<span class="pdf-badge pdf-badge-high">${escHtml(txt)}</span>`;
        } else if (/^(medium|orta)$/i.test(txt)) {
          cell.innerHTML = `<span class="pdf-badge pdf-badge-medium">${escHtml(txt)}</span>`;
        } else if (/^(low|düşük)$/i.test(txt)) {
          cell.innerHTML = `<span class="pdf-badge pdf-badge-low">${escHtml(txt)}</span>`;
        }
        if (/^\$?\d{1,3}(,\d{3})*(\.\d{2})?%?$/.test(txt)) {
          cell.classList.add('col-num');
        }
      });
    });
  });

  // 2. Add Section Numbers to H2 elements
  let sectionIndex = 0;
  const h2s = container.querySelectorAll('h2');
  h2s.forEach(h2 => {
    const text = h2.textContent.toLowerCase();
    if (text.includes('cover page') || text.includes('overview')) return;
    sectionIndex++;
    const num = sectionIndex < 10 ? `0${sectionIndex}` : `${sectionIndex}`;
    h2.setAttribute('data-section-num', num);
  });

  // 3. Wrap narrative paragraphs in a content div for better spacing
  container.querySelectorAll('p').forEach(p => {
    if (p.parentNode === container) {
      p.classList.add('pdf-paragraph');
    }
  });

  return container.innerHTML;
}

async function exportProposalPDF() {
  if (!proposalState.activeProposalId) return;

  // Open window synchronously to bypass browser popup blockers
  const printWindow = window.open('', '_blank');
  if (printWindow) {
    printWindow.document.write(`
      <!DOCTYPE html>
      <html>
      <head><title>Generating Proposal PDF...</title></head>
      <body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif; text-align:center; padding:60px; color:#334155;">
        <h2 style="font-size:20px; color:#0f172a;">Preparing Document for Print...</h2>
        <p style="font-size:14px; color:#64748b;">Compiling structured proposal sections, logframe matrix, and financial summary.</p>
      </body>
      </html>
    `);
    printWindow.document.close();
  }

  try {
    const res = await api(`/api/proposals/${proposalState.activeProposalId}/export`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    if (!printWindow) {
      alert("Please allow popups to export PDF.");
      return;
    }

    const prop = proposalState.activeProposal || {};
    const compiledHtml = renderProposalToHtml(data.markdown);

    // Extract KPI summary values if available
    let bData = {};
    try { bData = typeof prop.beneficiary_data === 'string' ? JSON.parse(prop.beneficiary_data) : (prop.beneficiary_data || {}); } catch {}
    let totalDirectReach = "N/A";
    if (bData.total_direct) totalDirectReach = bData.total_direct;
    else if (bData.direct && typeof bData.direct === 'object') {
      const sum = (parseInt(bData.direct.women)||0) + (parseInt(bData.direct.men)||0) + (parseInt(bData.direct.children)||0);
      if (sum > 0) totalDirectReach = sum.toLocaleString();
    }

    let budgetVal = "N/A";
    try {
      const bObj = typeof prop.budget === 'string' ? JSON.parse(prop.budget) : (prop.budget || {});
      if (bObj.total) budgetVal = bObj.total;
    } catch {}

    const currentDateStr = new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });

    printWindow.document.open();
    printWindow.document.write(`
      <!DOCTYPE html>
      <html lang="en">
      <head>
        <title>${escHtml(data.title || 'Proposal Document')}</title>
        <meta charset="utf-8">
        <style>
          @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Playfair+Display:ital,wght@0,600;0,700;0,800;1,600&display=swap');
          
          @page {
            size: A4 portrait;
            margin: 18mm 14mm 18mm 14mm;
            @top-right {
              content: "Sightline Project Proposal";
              font-family: 'Inter', sans-serif;
              font-size: 7pt;
              font-weight: 500;
              color: #94a3b8;
            }
            @bottom-left {
              content: "Sightline Advisor Studio • Confidential Operational Proposal";
              font-family: 'Inter', sans-serif;
              font-size: 7pt;
              color: #94a3b8;
            }
            @bottom-right {
              content: "Page " counter(page);
              font-family: 'Inter', sans-serif;
              font-size: 7pt;
              font-weight: 600;
              color: #64748b;
            }
          }
          
          *, *::before, *::after { box-sizing: border-box; }

          body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            color: #1e293b;
            line-height: 1.6;
            font-size: 10.5pt;
            margin: 0;
            padding: 0;
            background: #fff;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
          }
          
          /* ── Cover Page ── */
          .print-cover-page {
            min-height: 93vh;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            page-break-after: always;
            padding: 20px 5px;
            position: relative;
          }

          .cover-watermark {
            position: absolute;
            top: 45%;
            left: 50%;
            transform: translate(-50%, -50%) rotate(-35deg);
            font-size: 120px;
            color: rgba(226, 232, 240, 0.4);
            font-weight: 800;
            font-family: 'Inter', sans-serif;
            z-index: 0;
            pointer-events: none;
            letter-spacing: 16px;
          }
          
          .cover-header {
            border-top: 5px solid #e8364e;
            padding-top: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
          }
          
          .cover-logo {
            font-weight: 800;
            font-size: 24px;
            color: #e8364e;
            letter-spacing: -0.5px;
            font-family: 'Inter', sans-serif;
          }
          
          .cover-logo span {
            color: #0f172a;
          }

          .cover-badge {
            background: #f1f5f9;
            border: 1px solid #cbd5e1;
            color: #0f172a;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 9pt;
            font-weight: 700;
            letter-spacing: 1px;
            text-transform: uppercase;
          }
          
          .cover-body {
            margin-top: 50px;
            flex-grow: 1;
            position: relative;
            z-index: 1;
          }
          
          .cover-tagline {
            font-size: 10pt;
            text-transform: uppercase;
            letter-spacing: 3px;
            color: #e8364e;
            font-weight: 700;
            margin-bottom: 16px;
            display: block;
          }
          
          .cover-title {
            font-family: 'Playfair Display', serif;
            font-size: 34pt;
            font-weight: 800;
            line-height: 1.15;
            color: #0f172a;
            margin: 0 0 30px 0;
            max-width: 95%;
            letter-spacing: -0.5px;
          }
          
          .cover-metadata-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 16px 28px;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-left: 4px solid #0f172a;
            border-radius: 6px;
            padding: 20px;
            margin-top: 32px;
          }
          
          .cover-meta-item {
            display: flex;
            flex-direction: column;
            gap: 3px;
          }
          
          .cover-meta-item strong {
            font-size: 8pt;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #64748b;
            font-weight: 700;
          }
          
          .cover-meta-item span {
            font-size: 11pt;
            color: #0f172a;
            font-weight: 600;
          }
          
          .cover-footer {
            font-size: 9pt;
            color: #64748b;
            border-top: 1px solid #e2e8f0;
            padding-top: 16px;
            display: flex;
            justify-content: space-between;
            font-weight: 500;
          }

          .cover-footer .confidential {
            color: #e8364e;
            font-weight: 700;
            letter-spacing: 1px;
            text-transform: uppercase;
          }
          
          /* ── Executive KPI Grid ── */
          .pdf-kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
            margin: 0 0 24px 0;
            page-break-inside: avoid;
            page-break-after: avoid;
          }

          .pdf-kpi-card {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-top: 3px solid #e8364e;
            border-radius: 5px;
            padding: 10px 10px;
            display: flex;
            flex-direction: column;
            gap: 3px;
          }

          .pdf-kpi-card .kpi-label {
            font-size: 7.5pt;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: #64748b;
            font-weight: 700;
          }

          .pdf-kpi-card .kpi-val {
            font-size: 12pt;
            font-weight: 800;
            color: #0f172a;
          }

          /* ── Document Content & Headings ── */
          .proposal-content {
            padding-top: 0;
          }

          h1 {
            font-family: 'Playfair Display', serif;
            font-size: 22pt;
            font-weight: 700;
            margin-bottom: 16px;
            color: #0f172a;
            border-bottom: 2px solid #0f172a;
            padding-bottom: 8px;
            page-break-after: avoid;
          }

          h2 {
            font-family: 'Inter', sans-serif;
            font-size: 13pt;
            font-weight: 700;
            color: #0f172a;
            border-bottom: 1.5px solid #e2e8f0;
            padding-bottom: 5px;
            margin-top: 28px;
            margin-bottom: 12px;
            position: relative;
            padding-left: 10px;
            border-left: 4px solid #e8364e;
            page-break-after: avoid;
            page-break-inside: avoid;
          }

          h2[data-section-num]::before {
            content: attr(data-section-num) ". ";
            color: #e8364e;
            font-weight: 800;
          }
          
          /* Only force page break before major new sections, not every h2 */
          .proposal-content > h2:nth-of-type(n+3) {
            page-break-before: auto;
          }

          h3 {
            font-family: 'Inter', sans-serif;
            font-size: 11pt;
            font-weight: 700;
            margin-top: 16px;
            margin-bottom: 8px;
            color: #1e293b;
            page-break-after: avoid;
          }
          
          p, .pdf-paragraph {
            margin: 0 0 10px 0;
            text-align: justify;
            color: #334155;
            orphans: 3;
            widows: 3;
          }
          
          /* ── Table Styles ── */
          .pdf-table-wrapper {
            page-break-inside: avoid;
            margin: 14px 0 20px 0;
            overflow: hidden;
          }

          table, .pdf-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 8.5pt;
            page-break-inside: auto;
            border: 1px solid #d1d5db;
            border-radius: 0;
            box-shadow: none;
          }

          thead {
            display: table-header-group;
          }

          tbody {
            display: table-row-group;
          }

          tr {
            page-break-inside: avoid;
            page-break-after: auto;
          }

          th {
            background-color: #0f172a;
            color: #f8fafc;
            font-weight: 700;
            font-size: 7.5pt;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            text-align: left;
            padding: 7px 8px;
            border-bottom: 2px solid #e8364e;
            white-space: nowrap;
          }
          
          td {
            padding: 6px 8px;
            border-bottom: 1px solid #e5e7eb;
            color: #334155;
            vertical-align: top;
            line-height: 1.45;
            word-wrap: break-word;
            overflow-wrap: break-word;
            hyphens: auto;
          }
          
          tr:nth-child(even) td {
            background-color: #f9fafb;
          }

          tr.total-row td {
            background-color: #f1f5f9 !important;
            font-weight: 800;
            color: #0f172a;
            border-top: 2px solid #0f172a;
            border-bottom: 2px double #0f172a;
          }

          td.col-num, th.col-num {
            text-align: right;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
          }

          /* Badges */
          .pdf-badge {
            display: inline-block;
            padding: 1px 6px;
            border-radius: 10px;
            font-size: 7.5pt;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.3px;
            line-height: 1.6;
          }

          .pdf-badge-high {
            background-color: #fee2e2;
            color: #991b1b;
            border: 1px solid #fca5a5;
          }

          .pdf-badge-medium {
            background-color: #fef3c7;
            color: #92400e;
            border: 1px solid #fcd34d;
          }

          .pdf-badge-low {
            background-color: #dcfce7;
            color: #166534;
            border: 1px solid #86efac;
          }

          /* Callouts & Quotes */
          blockquote {
            margin: 12px 0;
            padding: 10px 14px;
            background: #fff5f5;
            border-left: 4px solid #e8364e;
            border-radius: 0 4px 4px 0;
            color: #1e293b;
            font-style: italic;
            page-break-inside: avoid;
          }
          
          ul, ol {
            margin: 8px 0;
            padding-left: 18px;
            color: #334155;
          }
          
          li {
            margin-bottom: 4px;
          }
          
          li::marker {
            color: #e8364e;
            font-weight: bold;
          }

          strong {
            color: #0f172a;
            font-weight: 600;
          }

          /* Ensure content blocks stay together */
          .proposal-content > *:first-child {
            margin-top: 0;
          }

          /* Metadata items at top (country, donor, etc.) */
          .proposal-content > p:first-of-type {
            margin-bottom: 8px;
            line-height: 1.8;
          }

          @media print {
            .no-print { display: none; }
            body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
          }
        </style>
      </head>
      <body>
        <div class="print-cover-page">
          <div class="cover-watermark">DRAFT</div>
          <div class="cover-header">
            <div class="cover-logo">Sight<span>line</span></div>
            <div class="cover-badge">Project Design Document</div>
          </div>
          <div class="cover-body">
            <span class="cover-tagline">Humanitarian Action Proposal</span>
            <h1 class="cover-title">${escHtml(prop.title || 'Untitled Proposal')}</h1>
            
            <div class="cover-metadata-grid">
              <div class="cover-meta-item">
                <strong>Country of Operation</strong>
                <span>${escHtml(prop.country || 'N/A')}</span>
              </div>
              <div class="cover-meta-item">
                <strong>Target Donor</strong>
                <span>${escHtml(prop.donor || 'N/A')}</span>
              </div>
              <div class="cover-meta-item">
                <strong>Sector & Focus</strong>
                <span>${escHtml(prop.event || 'Emergency Response')}</span>
              </div>
              <div class="cover-meta-item">
                <strong>Date Generated</strong>
                <span>${currentDateStr}</span>
              </div>
            </div>
          </div>
          <div class="cover-footer">
            <span>Prepared by Sightline Advisor Studio</span>
            <span class="confidential">Confidential Draft</span>
          </div>
        </div>

        <!-- Executive Dashboard Banner -->
        <div class="pdf-kpi-grid">
          <div class="pdf-kpi-card">
            <span class="kpi-label">Target Country</span>
            <span class="kpi-val">${escHtml(prop.country || 'N/A')}</span>
          </div>
          <div class="pdf-kpi-card">
            <span class="kpi-label">Target Donor</span>
            <span class="kpi-val">${escHtml(prop.donor || 'N/A')}</span>
          </div>
          <div class="pdf-kpi-card">
            <span class="kpi-label">Direct Reach</span>
            <span class="kpi-val">${escHtml(totalDirectReach)}</span>
          </div>
          <div class="pdf-kpi-card">
            <span class="kpi-label">Proposed Budget</span>
            <span class="kpi-val">${escHtml(budgetVal)}</span>
          </div>
        </div>
        
        <div class="proposal-content">
          ${compiledHtml}
        </div>
        
        <script>
          window.onload = function() {
            setTimeout(function() {
              window.print();
            }, 600);
          };
        </script>
      </body>
      </html>
    `);
    printWindow.document.close();
  } catch (err) {
    if (printWindow) printWindow.close();
    alert("PDF Export failed: " + err.message);
  }
}

