import React, { useEffect, useRef } from 'react';
import { Trash2, AlertTriangle, X } from 'lucide-react';
import { useI18n } from '../i18nContext';

export interface ConfirmModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  title: string;
  message: React.ReactNode;
  confirmText?: string;
  cancelText?: string;
  variant?: 'danger' | 'warning' | 'primary';
  isLoading?: boolean;
}

export const ConfirmModal: React.FC<ConfirmModalProps> = React.memo(({
  isOpen,
  onClose,
  onConfirm,
  title,
  message,
  confirmText,
  cancelText,
  variant = 'danger',
  isLoading = false,
}) => {
  const { t } = useI18n();
  const cancelBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isLoading) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);

    const timer = setTimeout(() => {
      cancelBtnRef.current?.focus();
    }, 40);

    return () => {
      document.body.style.overflow = originalOverflow;
      window.removeEventListener('keydown', handleKeyDown);
      clearTimeout(timer);
    };
  }, [isOpen, isLoading, onClose]);

  if (!isOpen) return null;

  const iconBg =
    variant === 'danger'
      ? 'bg-[var(--error-tonal)] text-[var(--error)] border border-[var(--error)]/25'
      : variant === 'warning'
      ? 'bg-[var(--warn-tonal)] text-[var(--warn-on-tonal)] border border-[var(--warn)]/25'
      : 'bg-[var(--accent-tonal)] text-[var(--accent-on-tonal)] border border-[var(--accent)]/25';

  const confirmBtnClass =
    variant === 'danger'
      ? 'bg-[var(--error)] hover:bg-[#b01e1b] text-white'
      : variant === 'warning'
      ? 'bg-[var(--warn)] hover:bg-[#e09a00] text-black font-semibold'
      : 'bg-[var(--accent)] hover:bg-[#1557b0] text-white';

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/45 backdrop-blur-md animate-[backdropFadeIn_0.2s_ease-out]"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isLoading) {
          onClose();
        }
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-modal-title"
    >
      <div
        className="relative w-full max-w-[440px] bg-[var(--bg)] border border-[var(--border-strong)] rounded-[28px] p-6 shadow-[0_24px_48px_rgba(32,33,36,0.18),0_4px_12px_rgba(32,33,36,0.08)] animate-[rise_0.25s_cubic-bezier(0.2,0.7,0.2,1)_both]"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={onClose}
          disabled={isLoading}
          className="absolute top-4 right-4 w-8 h-8 rounded-full flex items-center justify-center text-[var(--text-2)] hover:text-[var(--text)] hover:bg-[var(--surface-tonal)] transition-colors cursor-pointer disabled:opacity-50"
          aria-label={t('btn_close_modal')}
        >
          <X size={18} />
        </button>

        <div className="flex items-start gap-4">
          <div className={`w-12 h-12 rounded-2xl flex items-center justify-center flex-shrink-0 ${iconBg}`}>
            {variant === 'danger' ? (
              <Trash2 size={22} />
            ) : (
              <AlertTriangle size={22} />
            )}
          </div>

          <div className="min-w-0 flex-1 pt-0.5">
            <h3 id="confirm-modal-title" className="text-[17px] font-semibold text-[var(--text)] leading-snug tracking-tight">
              {title}
            </h3>
            <div className="mt-2 text-[13.5px] text-[var(--text-2)] leading-relaxed">
              {message}
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2.5 mt-6 pt-2">
          <button
            ref={cancelBtnRef}
            type="button"
            onClick={onClose}
            disabled={isLoading}
            className="h-10 px-5 rounded-full border border-[var(--border-strong)] bg-[var(--bg)] text-[var(--text)] hover:bg-[var(--surface-tonal)] text-[13.5px] font-medium transition-colors cursor-pointer disabled:opacity-50"
          >
            {cancelText || t('modal_btn_cancel')}
          </button>
          <button
            type="button"
            onClick={() => void onConfirm()}
            disabled={isLoading}
            className={`h-10 px-5 rounded-full text-[13.5px] font-medium shadow-sm flex items-center justify-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50 ${confirmBtnClass}`}
          >
            {isLoading && (
              <span className="w-3.5 h-3.5 border-2 border-white/60 border-t-white rounded-full animate-spin" />
            )}
            <span>{confirmText || t('settings_action_delete')}</span>
          </button>
        </div>
      </div>
    </div>
  );
});
