import type { Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

export type AuditFinding = {
  severity: 'FAIL' | 'WARN';
  rule: string;
  selector: string;
  detail: string;
};

export type GeometryAuditReport = {
  route: string;
  viewport: { width: number; height: number };
  passes: string[];
  findings: AuditFinding[];
};

export async function runGeometryAudit(page: Page, route: string): Promise<GeometryAuditReport> {
  const report = await page.evaluate(() => {
    const findings: AuditFinding[] = [];
    const passes: string[] = [];
    const viewport = { width: window.innerWidth, height: window.innerHeight };
    const nodes = Array.from(document.querySelectorAll<HTMLElement>('*'));
    const meaningful = nodes.filter((node) => {
      const style = getComputedStyle(node);
      return style.display !== 'none' && style.visibility !== 'hidden' && node.getClientRects().length > 0;
    });
    const selectorFor = (node: Element) => {
      if (node.id) return `#${node.id}`;
      if (node.classList.length) return `.${Array.from(node.classList).slice(0, 2).join('.')}`;
      return node.tagName.toLowerCase();
    };
    const intersects = (a: DOMRect, b: DOMRect) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;

    const overflowing = meaningful.filter((node) => {
      const rect = node.getBoundingClientRect();
      return rect.right > viewport.width + 1 || rect.left < -1;
    });
    if (document.documentElement.scrollWidth <= viewport.width + 1) passes.push('horizontal overflow');
    else findings.push({ severity: 'FAIL', rule: 'horizontal-overflow', selector: 'document', detail: `scrollWidth ${document.documentElement.scrollWidth}px > viewport ${viewport.width}px` });
    if (!overflowing.length) passes.push('viewport bounds');
    overflowing.slice(0, 10).forEach((node) => {
      const rect = node.getBoundingClientRect();
      findings.push({ severity: 'FAIL', rule: 'viewport-bounds', selector: selectorFor(node), detail: `${Math.round(rect.left)}..${Math.round(rect.right)} outside ${viewport.width}px` });
    });

    const smallTargets = meaningful.filter((node) => {
      if (!(node.matches('button, a, input, select, textarea, [role="button"]'))) return false;
      const rect = node.getBoundingClientRect();
      return rect.width < 40 || rect.height < 40;
    });
    if (!smallTargets.length) passes.push('touch targets');
    smallTargets.slice(0, 10).forEach((node) => findings.push({ severity: 'WARN', rule: 'touch-target', selector: selectorFor(node), detail: `${Math.round(node.getBoundingClientRect().width)}×${Math.round(node.getBoundingClientRect().height)}px` }));

    const clippedText = meaningful.filter((node) => {
      const style = getComputedStyle(node);
      return style.overflow === 'hidden' && node.scrollWidth > node.clientWidth + 1 && node.textContent?.trim();
    });
    if (!clippedText.length) passes.push('text clipping');
    clippedText.slice(0, 10).forEach((node) => findings.push({ severity: 'WARN', rule: 'text-clipping', selector: selectorFor(node), detail: 'meaningful text is clipped by overflow:hidden' }));

    const bentoCards = meaningful.filter((node) => node.matches('.bs-dashboard-card, .bs-dashboard-metric, .bs-dashboard-goal-card') && !node.matches('.bs-dashboard-hero-card'));
    const emptySpaceCards = bentoCards.filter((card) => {
      const cardRect = card.getBoundingClientRect();
      if (cardRect.height < 180) return false;
      const contentRects = Array.from(card.querySelectorAll<HTMLElement>('*')).filter((child) => {
        const style = getComputedStyle(child);
        return style.position !== 'absolute' && style.position !== 'fixed' && style.display !== 'none' && child.getClientRects().length > 0;
      }).map((child) => child.getBoundingClientRect()).filter((rect) => rect.width > 0 && rect.height > 0);
      if (!contentRects.length) return true;
      const contentTop = Math.min(...contentRects.map((rect) => rect.top));
      const contentBottom = Math.max(...contentRects.map((rect) => rect.bottom));
      const contentHeight = Math.max(0, contentBottom - contentTop);
      return contentHeight < cardRect.height * 0.55;
    });
    if (!emptySpaceCards.length) passes.push('excessive empty space');
    emptySpaceCards.slice(0, 10).forEach((node) => findings.push({ severity: 'WARN', rule: 'excessive-empty-space', selector: selectorFor(node), detail: `content occupies less than 55% of ${Math.round(node.getBoundingClientRect().height)}px card height` }));

    const fixed = meaningful.filter((node) => ['fixed', 'sticky'].includes(getComputedStyle(node).position));
    const actions = meaningful.filter((node) => node.matches('button, a, input, select, textarea, [role="button"]'));
    let overlapCount = 0;
    fixed.forEach((fixedNode) => {
      // The mobile bottom navigation intentionally overlays the scroll surface;
      // its opaque bar is the canonical touch affordance, not an accidental overlap.
      if (fixedNode.matches('.bs-dashboard-mobile-nav')) return;
      const fixedRect = fixedNode.getBoundingClientRect();
      actions.forEach((action) => {
        if (fixedNode === action || fixedNode.contains(action) || action.contains(fixedNode)) return;
        if (intersects(fixedRect, action.getBoundingClientRect())) {
          overlapCount += 1;
          if (overlapCount <= 10) findings.push({ severity: 'FAIL', rule: 'fixed-overlap', selector: selectorFor(fixedNode), detail: `intersects ${selectorFor(action)}` });
        }
      });
    });
    if (!overlapCount) passes.push('fixed overlaps');

    const suspiciousZ = meaningful.filter((node) => Number.parseInt(getComputedStyle(node).zIndex, 10) > 1000);
    if (suspiciousZ.length) suspiciousZ.slice(0, 10).forEach((node) => findings.push({ severity: 'WARN', rule: 'z-index', selector: selectorFor(node), detail: `z-index ${getComputedStyle(node).zIndex}` }));
    else passes.push('z-index');

    const canonicalRadii = new Set(['0px', '10px', '14px', '20px', '28px', '9999px']);
    const arbitraryRadii = meaningful.filter((node) => {
      const radius = getComputedStyle(node).borderRadius;
      return radius !== '0px' && !canonicalRadii.has(radius) && !radius.includes('%');
    });
    arbitraryRadii.slice(0, 10).forEach((node) => findings.push({ severity: 'WARN', rule: 'token-radius', selector: selectorFor(node), detail: `border-radius ${getComputedStyle(node).borderRadius}` }));
    if (!arbitraryRadii.length) passes.push('canonical radii');

    return { route: window.location.pathname, viewport, passes, findings };
  });
  const outputDir = path.resolve('artifacts', 'visual', route.replace(/^\//, '').replace(/\//g, '_') || 'page');
  fs.mkdirSync(outputDir, { recursive: true });
  const reportPath = path.join(outputDir, `${report.viewport.width}x${report.viewport.height}.json`);
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
  const fails = report.findings.filter((finding) => finding.severity === 'FAIL').length;
  console.log(`VISUAL QA — ${report.route} — ${report.viewport.width}×${report.viewport.height}: ${fails} FAIL, ${report.findings.length - fails} WARN, ${report.passes.length} PASS`);
  return report;
}
