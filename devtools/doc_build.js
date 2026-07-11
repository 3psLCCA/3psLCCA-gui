/**
 * doc_build.js
 *
 * Generates complete, standalone HTML files from Markdown docs.
 * Each output file is self-contained: inline CSS, baked-in sidebar, pre-rendered math.
 * No JS is required to read the content - JS only adds theme adaptation + app navigation.
 *
 * Math rendering:
 *   katex   → MathML  (browser-native, no CSS or fonts needed)
 *   mathjax → SVG     (self-contained, no external deps)
 *
 * Usage:
 *   node doc_build.js <renderer> <docs_dir> <build_dir>
 *
 * Stdout protocol (read by Python builder):
 *   FILE <rel-path>        - file being written
 *   DONE <n> <elapsed_ms>  - finished
 *   ERROR <message>        - fatal error
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const { marked } = require('marked');

const RENDERER = process.argv[2] || 'katex';
const DOCS_DIR  = path.resolve(process.argv[3] || '');
const BUILD_DIR = path.resolve(process.argv[4] || '');

if (!DOCS_DIR || !BUILD_DIR) {
    process.stdout.write('ERROR Usage: node doc_build.js <renderer> <docs_dir> <build_dir>\n');
    process.exit(1);
}

// ── Math renderer (init once) ──────────────────────────────────────────────────

let renderMath;

if (RENDERER === 'katex') {
    const katex = require('katex');
    // output:'mathml' → pure MathML, no CSS or font files required
    renderMath = (expr, display) =>
        katex.renderToString(expr, { displayMode: display, throwOnError: false, output: 'mathml' });
} else {
    const { mathjax }             = require('mathjax-full/js/mathjax.js');
    const { TeX }                 = require('mathjax-full/js/input/tex.js');
    const { SVG }                 = require('mathjax-full/js/output/svg.js');
    const { liteAdaptor }         = require('mathjax-full/js/adaptors/liteAdaptor.js');
    const { RegisterHTMLHandler } = require('mathjax-full/js/handlers/html.js');
    const { AllPackages }         = require('mathjax-full/js/input/tex/AllPackages.js');

    const adaptor = liteAdaptor();
    RegisterHTMLHandler(adaptor);
    const mjDoc = mathjax.document('', {
        InputJax: new TeX({ packages: AllPackages }),
        OutputJax: new SVG({ fontCache: 'none' }),   // SVG carries all glyph data inline
    });
    renderMath = (expr, display) => adaptor.outerHTML(mjDoc.convert(expr, { display }));
}

// ── Markdown + math conversion ─────────────────────────────────────────────────

const CODE_FENCE_RE = /```[\s\S]*?```|~~~[\s\S]*?~~~/g;
const CODE_SPAN_RE  = /`[^`\n]+`/g;
const DISPLAY_RE    = /\$\$([\s\S]+?)\$\$/g;  // before INLINE_RE - avoids treating $$ as two $
const INLINE_RE     = /\$([^$\n]+?)\$/g;

function convertMd(md) {
    // 1. Guard code blocks so $...$ inside them is never touched
    const guards = new Map(); let gi = 0;
    const guard = m => { const k = `\x00G${gi++}\x00`; guards.set(k, m); return k; };
    md = md.replace(CODE_FENCE_RE, guard).replace(CODE_SPAN_RE, guard);

    // 2. Extract math into placeholders safe from marked
    const mathMap = new Map(); let mi = 0;
    md = md.replace(DISPLAY_RE, (_, e) => {
        const k = `\x00M${mi++}\x00`; mathMap.set(k, { e: e.trim(), d: true }); return k;
    });
    md = md.replace(INLINE_RE, (_, e) => {
        const k = `\x00M${mi++}\x00`; mathMap.set(k, { e: e.trim(), d: false }); return k;
    });

    // 3. Restore code blocks before marked processes them
    for (const [k, v] of guards) md = md.split(k).join(v);

    // 4. Markdown → HTML
    let html = marked.parse(md);

    // 5. Replace math placeholders with pre-rendered output
    for (const [k, { e, d }] of mathMap) {
        let rendered;
        try { rendered = renderMath(e, d); }
        catch (_) { rendered = d ? `$$${e}$$` : `$${e}$`; }
        html = html.split(k).join(
            d ? `<div class="math-display">${rendered}</div>` : rendered
        );
    }
    return html;
}

// ── Tree builder ───────────────────────────────────────────────────────────────

function buildTree() {
    const tree = [];
    for (const dirName of fs.readdirSync(DOCS_DIR).sort()) {
        const catPath = path.join(DOCS_DIR, dirName);
        if (!fs.statSync(catPath).isDirectory()) continue;
        const mdFiles = fs.readdirSync(catPath)
            .filter(f => f.endsWith('.md') && f !== '404.md' && !f.startsWith('_')).sort();
        if (!mdFiles.length) continue;
        const items = mdFiles.map(f => {
            const src = fs.readFileSync(path.join(catPath, f), 'utf8');
            const h1  = src.match(/^#\s+(.+)/m);
            return {
                label:    h1 ? h1[1].trim() : f.slice(0, -3).replace(/_/g, ' '),
                mdRel:    `${dirName}/${f}`,
                htmlRel:  `${dirName}/${f.slice(0, -3)}.html`,
            };
        });
        const label = dirName.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        tree.push({ label, dirName, items });
    }
    return tree;
}

// ── Sidebar HTML ───────────────────────────────────────────────────────────────

function makeSidebar(tree, currentHtmlRel) {
    let out = '';
    for (const cat of tree) {
        out += `<div class="nav-section"><div class="nav-group">${esc(cat.label)}</div>`;
        for (const item of cat.items) {
            // All pages live one level deep, so '../Cat/Page.html' always resolves correctly.
            const href = '../' + item.htmlRel;
            const cls  = item.htmlRel === currentHtmlRel ? 'nav-item active' : 'nav-item';
            out += `<a class="${cls}" href="${href}">${esc(item.label)}</a>`;
        }
        out += `</div>`;
    }
    return out;
}

// ── HTML template ──────────────────────────────────────────────────────────────

const CSS = fs.readFileSync(path.join(__dirname, 'doc_template.css'), 'utf8').trim();
const JS  = fs.readFileSync(path.join(__dirname, 'doc_template.js'),  'utf8').trim();

const FAVICON = (() => {
    try {
        const p = path.resolve(__dirname, '..', 'src', 'three_ps_lcca_gui',
                               'gui', 'assets', 'logo', 'logo-3psLCCA.svg');
        const b64 = fs.readFileSync(p).toString('base64');
        return `<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,${b64}">`;
    } catch (_) { return ''; }
})();

function makeHTML(title, sidebar, content) {
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>
${FAVICON}
<style>${CSS}</style>
</head>
<body>
<aside id="sidebar">
  <div class="search-wrap">
    <input id="search" type="text" placeholder="Search…" autocomplete="off">
  </div>
  <nav id="nav">${sidebar}</nav>
</aside>
<main id="content">${content}</main>
<script>${JS}</script>
</body>
</html>`;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function esc(s) {
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Main ───────────────────────────────────────────────────────────────────────

try {
    const t0 = Date.now();
    fs.mkdirSync(BUILD_DIR, { recursive: true });

    const tree = buildTree();
    let n = 0;

    for (const cat of tree) {
        const catDir = path.join(BUILD_DIR, cat.dirName);
        fs.mkdirSync(catDir, { recursive: true });

        for (const item of cat.items) {
            process.stdout.write(`FILE ${item.mdRel}\n`);

            const md      = fs.readFileSync(path.join(DOCS_DIR, item.mdRel), 'utf8');
            const h1      = md.match(/^#\s+(.+)/m);
            const title   = h1 ? h1[1].trim() : item.label;
            const content = convertMd(md);
            const sidebar = makeSidebar(tree, item.htmlRel);
            const html    = makeHTML(title, sidebar, content);

            fs.writeFileSync(path.join(BUILD_DIR, item.htmlRel), html, 'utf8');
            n++;
        }
    }

    fs.writeFileSync(
        path.join(BUILD_DIR, 'build_info.json'),
        JSON.stringify({ renderer: RENDERER }),
    );

    process.stdout.write(`DONE ${n} ${Date.now() - t0}\n`);

} catch (err) {
    process.stdout.write(`ERROR ${err.message}\n`);
    process.exit(1);
}
