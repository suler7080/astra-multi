import React, { useRef, useState, useEffect, useCallback } from 'react';
import { Check, AlertTriangle, ChevronLeft, ChevronRight } from 'lucide-react';
import { useI18n } from '../i18nContext';

const PHASES = [
  'INTAKE',
  'SNAPSHOT',
  'INVESTIGATE',
  'INDEPENDENT_ANALYSIS',
  'PROPOSE',
  'REVIEW',
  'VERIFY',
  'REVISE',
  'SEMANTIC_REVIEW',
  'QUALITY_GATE',
  'EXPORT',
] as const;

interface PhaseTrackerProps {
  currentPhase: string;
  status: string;
  stopReason?: string | null;
}

export const PhaseTracker: React.FC<PhaseTrackerProps> = React.memo(({
  currentPhase,
  status,
  stopReason,
}) => {
  const { t } = useI18n();
  const currentIndex = PHASES.indexOf(currentPhase as (typeof PHASES)[number]);
  const activeIndex = status === 'FINAL' ? 11 : currentIndex >= 0 ? currentIndex + 1 : 1;

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const activePhaseRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  // Mouse drag-to-scroll state
  const [isDragging, setIsDragging] = useState(false);
  const startXRef = useRef(0);
  const scrollLeftRef = useRef(0);

  const getPhaseDisplay = (idx: number, phase: string) => {
    const num = String(idx + 1).padStart(2, '0');
    return `${num} ${phase.replace('_', ' ')}`;
  };

  const checkScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    setCanScrollLeft(el.scrollLeft > 8);
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 8);
  }, []);

  useEffect(() => {
    checkScroll();
    const el = scrollContainerRef.current;
    if (!el) return;
    el.addEventListener('scroll', checkScroll, { passive: true });
    window.addEventListener('resize', checkScroll);
    return () => {
      el.removeEventListener('scroll', checkScroll);
      window.removeEventListener('resize', checkScroll);
    };
  }, [checkScroll]);

  // Automatically scroll active phase into view smoothly
  useEffect(() => {
    const timer = setTimeout(() => {
      if (activePhaseRef.current && scrollContainerRef.current) {
        activePhaseRef.current.scrollIntoView({
          behavior: 'smooth',
          block: 'nearest',
          inline: 'center',
        });
      }
      checkScroll();
    }, 100);
    return () => clearTimeout(timer);
  }, [currentPhase, status, checkScroll]);

  const handleScroll = (direction: 'left' | 'right') => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const scrollAmount = Math.max(260, Math.floor(el.clientWidth * 0.6));
    el.scrollBy({
      left: direction === 'left' ? -scrollAmount : scrollAmount,
      behavior: 'smooth',
    });
  };

  const onMouseDown = (e: React.MouseEvent) => {
    const el = scrollContainerRef.current;
    if (!el) return;
    setIsDragging(true);
    startXRef.current = e.pageX - el.offsetLeft;
    scrollLeftRef.current = el.scrollLeft;
  };

  const onMouseLeave = () => {
    setIsDragging(false);
  };

  const onMouseUp = () => {
    setIsDragging(false);
  };

  const onMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return;
    const el = scrollContainerRef.current;
    if (!el) return;
    e.preventDefault();
    const x = e.pageX - el.offsetLeft;
    const walk = (x - startXRef.current) * 1.5;
    el.scrollLeft = scrollLeftRef.current - walk;
  };

  return (
    <div className="bg-[var(--bg)] border border-[var(--border)] rounded-[28px] p-6 shadow-sm mb-7">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-3">
          <h3 className="text-[16px] font-medium text-[var(--text)] tracking-tight">
            {t('phase_stepper_progress').replace('{current}', String(activeIndex).padStart(2, '0'))}
          </h3>

          {/* Quick Slider Arrow Controls */}
          <div className="flex items-center gap-1 bg-[var(--surface-tonal)] rounded-full p-0.5 border border-[var(--border)]">
            <button
              type="button"
              onClick={() => handleScroll('left')}
              disabled={!canScrollLeft}
              className="w-7 h-7 rounded-full flex items-center justify-center text-[var(--text-2)] hover:text-[var(--text)] hover:bg-[var(--bg)] disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer"
              title="Cuộn sang trái"
              aria-label="Cuộn sang trái"
            >
              <ChevronLeft size={16} />
            </button>
            <button
              type="button"
              onClick={() => handleScroll('right')}
              disabled={!canScrollRight}
              className="w-7 h-7 rounded-full flex items-center justify-center text-[var(--text-2)] hover:text-[var(--text)] hover:bg-[var(--bg)] disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer"
              title="Cuộn sang phải"
              aria-label="Cuộn sang phải"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>

        {stopReason && (
          <div
            className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[var(--error-tonal)] text-[var(--error-on-tonal)] text-[12px] font-mono border border-[var(--error)]/20"
            title={stopReason}
          >
            <AlertTriangle size={13} className="text-[var(--error)]" />
            <span className="font-semibold">{t('phase_stop_reason')}:</span>
            <span className="truncate max-w-xs sm:max-w-md">{stopReason}</span>
          </div>
        )}
      </div>

      {/* 11 Horizontal Pills Stepper with Custom Track & Drag Slider */}
      <div className="relative">
        {/* Left fade hint */}
        {canScrollLeft && (
          <div className="pointer-events-none absolute left-0 top-0 bottom-3 w-8 bg-gradient-to-r from-[var(--bg)] to-transparent z-10" />
        )}

        {/* Right fade hint */}
        {canScrollRight && (
          <div className="pointer-events-none absolute right-0 top-0 bottom-3 w-8 bg-gradient-to-r from-transparent to-[var(--bg)] z-10" />
        )}

        <div
          ref={scrollContainerRef}
          onMouseDown={onMouseDown}
          onMouseLeave={onMouseLeave}
          onMouseUp={onMouseUp}
          onMouseMove={onMouseMove}
          className={`flex items-center gap-2 overflow-x-auto pb-3 pt-1 phase-stepper-scroll select-none ${
            isDragging ? 'cursor-grabbing' : 'cursor-grab'
          }`}
          role="list"
        >
          {PHASES.map((phase, idx) => {
            const isDone = currentIndex > idx || status === 'FINAL';
            const isCurrent = currentIndex === idx && status !== 'FINAL';
            const label = getPhaseDisplay(idx, phase);

            if (isDone) {
              return (
                <div
                  key={phase}
                  role="listitem"
                  className="h-10 px-4 rounded-full bg-[var(--accent-tonal)] text-[var(--accent-on-tonal)] font-mono text-[12px] font-medium inline-flex items-center gap-1.5 shrink-0 select-none transition-colors"
                  title={`${label} (Đã xong)`}
                >
                  <Check size={14} className="stroke-[2.5]" aria-label="Đã xong" />
                  <span>{label}</span>
                </div>
              );
            }

            if (isCurrent) {
              return (
                <div
                  key={phase}
                  ref={activePhaseRef}
                  role="listitem"
                  aria-current="step"
                  className="h-10 px-4 rounded-full bg-[var(--accent)] text-white font-mono text-[12px] font-medium inline-flex items-center gap-1.5 shrink-0 select-none shadow-sm transition-colors"
                  title={`${label} (Đang chạy)`}
                >
                  <span>{label}</span>
                </div>
              );
            }

            return (
              <div
                key={phase}
                role="listitem"
                className="h-10 px-4 rounded-full border border-[var(--border-strong)] text-[var(--text-2)] bg-transparent font-mono text-[12px] font-medium inline-flex items-center gap-1.5 shrink-0 select-none hover:bg-[var(--surface-tonal)] transition-colors"
                title={label}
              >
                <span>{label}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
});
