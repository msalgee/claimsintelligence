import { useEffect, useRef, useState } from 'react';
import { Spinner, Caption1, tokens } from '@fluentui/react-components';
import * as pdfjsLib from 'pdfjs-dist';
import workerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

pdfjsLib.GlobalWorkerOptions.workerSrc = workerSrc;

interface Props {
  /** Object URL (blob:) or remote URL of the PDF. */
  src: string;
  /** Max viewport width to render at. Defaults to 800. */
  maxWidth?: number;
}

/**
 * Render every page of a PDF to a canvas using PDF.js.
 * Works in any Chromium build (no built-in PDF viewer required) and in
 * environments where `<iframe src="blob:.../pdf">` would otherwise trigger
 * a download prompt.
 */
export function PdfPreview({ src, maxWidth = 800 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const container = containerRef.current;
    if (container) container.innerHTML = '';

    (async () => {
      try {
        const loadingTask = pdfjsLib.getDocument({ url: src });
        const pdf = await loadingTask.promise;
        if (cancelled) return;
        for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
          const page = await pdf.getPage(pageNum);
          if (cancelled) return;
          const baseViewport = page.getViewport({ scale: 1 });
          const scale = Math.min(2, maxWidth / baseViewport.width);
          const viewport = page.getViewport({ scale });
          const canvas = document.createElement('canvas');
          canvas.width = Math.floor(viewport.width);
          canvas.height = Math.floor(viewport.height);
          canvas.style.maxWidth = '100%';
          canvas.style.height = 'auto';
          canvas.style.display = 'block';
          canvas.style.marginBottom = '12px';
          canvas.style.boxShadow = `0 1px 3px ${tokens.colorNeutralShadowAmbient}`;
          canvas.style.background = '#ffffff';
          const ctx = canvas.getContext('2d');
          if (!ctx) continue;
          if (container && !cancelled) container.appendChild(canvas);
          await page.render({ canvasContext: ctx, viewport }).promise;
        }
        if (!cancelled) setLoading(false);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [src, maxWidth]);

  return (
    <div>
      {loading && <Spinner label="Rendering PDF…" />}
      {error && (
        <Caption1 style={{ color: tokens.colorPaletteRedForeground1 }}>
          Could not render PDF: {error}
        </Caption1>
      )}
      <div ref={containerRef} />
    </div>
  );
}
