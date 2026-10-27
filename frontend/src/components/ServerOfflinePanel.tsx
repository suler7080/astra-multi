import React, { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import { useI18n } from '../i18nContext';

interface ServerOfflinePanelProps {
  countdown: number;
  totalCountdown?: number;
  onRetry?: () => void;
  isRetrying?: boolean;
}

export const ServerOfflinePanel: React.FC<ServerOfflinePanelProps> = ({
  countdown,
  totalCountdown = 10,
  onRetry,
  isRetrying = false,
}) => {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);

  const commandText = `cd backend\n.\\.venv\\Scripts\\python -m astra_multi.cli serve --port 8000`;

  const handleCopy = () => {
    navigator.clipboard.writeText(commandText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // SVG circular progress calculation
  const radius = 16;
  const circumference = 2 * Math.PI * radius;
  // Fraction remaining (0 to 1)
  const fraction = Math.max(0, Math.min(1, countdown / (totalCountdown || 10)));
  const strokeDashoffset = circumference * (1 - fraction);

  return (
    <div className="bg-white border border-[#DADCE0] rounded-[24px] p-6 sm:p-7 shadow-[0_1px_3px_rgba(60,64,67,.12),0_10px_28px_rgba(60,64,67,.10)] max-w-lg w-full relative z-10">
      <div className="flex items-center justify-between gap-3 mb-2">
        <h3 className="text-[19px] font-medium text-[#202124] tracking-tight">
          {t('conn_offline_title')}
        </h3>
        <span className="chip chip-error font-mono text-[11px] py-0.5 px-2.5">
          <span className="w-2 h-2 rounded-full bg-[var(--error)]" />
          Offline
        </span>
      </div>

      <p className="text-[14px] text-[#5F6368] mb-4">
        {t('conn_restart_help')}
      </p>

      {/* Code box */}
      <div className="relative bg-[#F1F3F4] rounded-[16px] p-4 mb-4 font-mono text-[13px] text-[#202124] leading-relaxed">
        <div className="pr-12 whitespace-pre-wrap break-all font-mono select-all">
          <div className="font-semibold text-[#202124]">cd backend</div>
          <div className="text-[#3C4043]">.\.venv\Scripts\python -m astra_multi.cli serve --port 8000</div>
        </div>
        <button
          type="button"
          onClick={handleCopy}
          className="absolute right-3 top-3 w-9 h-9 rounded-full flex items-center justify-center bg-white hover:bg-[#F8F9FA] text-[#5F6368] hover:text-[#202124] transition-colors border border-[#DADCE0] shadow-sm cursor-pointer"
          title={copied ? t('conn_copied') : t('conn_copy_command')}
          aria-label={copied ? t('conn_copied') : t('conn_copy_command')}
        >
          {copied ? <Check size={15} className="text-[#1E8E3E]" /> : <Copy size={15} />}
        </button>
        {copied && (
          <span className="absolute right-14 top-5 text-[11px] font-mono text-[var(--success-on-tonal)] font-medium" role="status" aria-live="polite">
            {t('conn_copied')}
          </span>
        )}
      </div>

      {/* Progress ring countdown */}
      <div className="flex items-center justify-between gap-3 pt-1">
        <div className="flex items-center gap-2.5">
          <div className="relative w-8 h-8 flex items-center justify-center shrink-0">
            <svg className="w-8 h-8 transform -rotate-90" viewBox="0 0 40 40">
              <circle
                cx="20"
                cy="20"
                r={radius}
                stroke="#E8EAED"
                strokeWidth="3.5"
                fill="transparent"
              />
              <circle
                cx="20"
                cy="20"
                r={radius}
                stroke="#1967D2"
                strokeWidth="3.5"
                fill="transparent"
                strokeDasharray={circumference}
                strokeDashoffset={strokeDashoffset}
                strokeLinecap="round"
                className="transition-all duration-1000 ease-linear"
              />
            </svg>
          </div>
          <span className="text-[13px] text-[#5F6368] font-medium">
            {t('conn_retrying_in').replace('{seconds}', String(countdown))}
          </span>
        </div>

        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            disabled={isRetrying}
            className="text-[13px] font-medium text-[#1967D2] hover:text-[#174EA6] hover:underline cursor-pointer bg-transparent border-none p-0 inline-flex items-center gap-1"
          >
            <span>{isRetrying ? t('conn_retrying') : t('conn_retry')}</span>
          </button>
        )}
      </div>
    </div>
  );
};

export default ServerOfflinePanel;
