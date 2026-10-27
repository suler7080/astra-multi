import React, { useState } from 'react';
import { AlertCircle, Loader2, X, ChevronDown, ChevronUp } from 'lucide-react';
import { useI18n } from '../i18nContext';

export interface GenericErrorInfo {
  message: string;
  details?: string;
  code?: string;
  status?: number;
  correlationId?: string;
}

interface ErrorBannerProps {
  connectionStatus: 'connected' | 'connecting' | 'offline';
  countdown: number;
  isRetrying: boolean;
  onRetry: () => void;
  genericError?: GenericErrorInfo | null;
  onDismissGenericError?: () => void;
}

export const ErrorBanner: React.FC<ErrorBannerProps> = ({
  connectionStatus,
  genericError,
  onDismissGenericError,
}) => {
  const { t } = useI18n();
  const [showDetails, setShowDetails] = useState(false);

  // 1. Connecting status
  if (connectionStatus === 'connecting') {
    return (
      <div className="max-w-[1280px] mx-auto px-8 pt-4" role="status" aria-live="polite">
        <div className="chip chip-warn py-2 px-4 shadow-sm">
          <Loader2 className="animate-spin" size={16} />
          <span>{t('conn_connecting')}</span>
        </div>
      </div>
    );
  }

  // 2. Generic Error display (styled in Google Error Tonal rounded 24px card)
  if (genericError) {
    return (
      <div className="max-w-[1280px] mx-auto px-8 pt-4" role="alert">
        <div className="bg-[var(--error-tonal)] text-[var(--error-on-tonal)] border border-[var(--error)]/20 rounded-[24px] p-5 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3">
              <AlertCircle size={20} className="text-[var(--error)] mt-0.5 shrink-0" />
              <div>
                <h4 className="font-medium text-[15px]">{genericError.message}</h4>
                {genericError.details && (
                  <button
                    type="button"
                    onClick={() => setShowDetails((prev) => !prev)}
                    className="inline-flex items-center gap-1 text-[13px] font-medium text-[var(--error-on-tonal)] underline hover:opacity-80 mt-1 cursor-pointer"
                  >
                    <span>{showDetails ? t('error_hide_details') : t('error_view_details')}</span>
                    {showDetails ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </button>
                )}
                {showDetails && genericError.details && (
                  <div className="mt-3 p-3 bg-white/60 border border-[var(--error)]/10 rounded-[16px] text-[12px] font-mono whitespace-pre-wrap break-all select-all">
                    <pre>{genericError.details}</pre>
                    {genericError.correlationId && (
                      <div className="mt-2 text-[11px] font-mono text-[var(--text-2)]">
                        {t('error_correlation_id')} {genericError.correlationId}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
            {onDismissGenericError && (
              <button
                type="button"
                onClick={onDismissGenericError}
                className="w-9 h-9 rounded-full flex items-center justify-center hover:bg-black/5 text-[var(--error-on-tonal)] transition-colors"
                aria-label={t('error_dismiss_label')}
              >
                <X size={18} />
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  return null;
};
