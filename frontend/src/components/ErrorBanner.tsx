import React, { useState } from 'react';
import { AlertCircle, AlertTriangle, Loader2, RefreshCw, X } from 'lucide-react';
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
  countdown,
  isRetrying,
  onRetry,
  genericError,
  onDismissGenericError,
}) => {
  const { t } = useI18n();
  const [showDetails, setShowDetails] = useState(false);

  // 1. Backend Offline / Connecting status takes priority
  if (connectionStatus === 'connecting') {
    return (
      <div className="connection-banner connection-connecting" role="status" aria-live="polite">
        <Loader2 className="animate-spin text-amber-400" size={18} />
        <span className="connection-connecting-text">{t('conn_connecting')}</span>
      </div>
    );
  }

  if (connectionStatus === 'offline') {
    return (
      <aside className="connection-banner connection-offline" role="status" aria-live="polite">
        <div className="connection-offline-body">
          <div className="connection-icon-wrapper">
            <AlertTriangle className="connection-icon" size={20} />
          </div>
          <div className="connection-offline-content">
            <h4 className="connection-offline-title">{t('conn_offline_title')}</h4>
            <p className="connection-offline-desc">{t('conn_offline_desc')}</p>
          </div>
        </div>
        <div className="connection-offline-actions">
          <span className="connection-countdown-badge">
            {t('conn_retrying_in').replace('{seconds}', String(countdown))}
          </span>
          <button
            type="button"
            onClick={onRetry}
            disabled={isRetrying}
            className="btn-retry-primary"
            aria-label={t('conn_retry')}
          >
            <RefreshCw size={14} className={isRetrying ? 'animate-spin' : ''} />
            <span>{isRetrying ? t('conn_retrying') : t('conn_retry')}</span>
          </button>
        </div>
      </aside>
    );
  }

  // 2. Generic Error display (not offline)
  if (genericError) {
    return (
      <div className="generic-error-banner" role="alert">
        <div className="generic-error-main">
          <AlertCircle className="generic-error-icon" size={18} />
          <div className="generic-error-text-container">
            <span className="generic-error-message">{genericError.message}</span>
            {genericError.details && (
              <button
                type="button"
                onClick={() => setShowDetails((prev) => !prev)}
                className="btn-error-details-toggle"
              >
                {showDetails ? t('error_hide_details') : t('error_view_details')}
              </button>
            )}
            {showDetails && genericError.details && (
              <div className="generic-error-details-box">
                <pre>{genericError.details}</pre>
                {genericError.correlationId && (
                  <div className="generic-error-correlation">
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
            className="btn-dismiss"
            aria-label={t('error_dismiss_label')}
          >
            <X size={16} />
          </button>
        )}
      </div>
    );
  }

  return null;
};
