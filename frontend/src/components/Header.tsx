import React from 'react';
import type { RunSummary } from '../types';
import { LogOut } from 'lucide-react';
import { LanguageSwitcher } from '../i18n';
import { useI18n } from '../i18nContext';

interface HeaderProps {
  runs: RunSummary[];
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
  onOpenNewRun: () => void;
  onRefresh: () => void;
  onOpenSettings: () => void;
  onLogout?: () => void;
  isLoading: boolean;
  isOffline?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  selectedRunId,
  onSelectRun,
  onOpenNewRun,
  onOpenSettings,
  onLogout,
  isOffline = false,
}) => {
  const { t } = useI18n();

  return (
    <header className="w-full bg-white border-b border-[#E8EAED] sticky top-0 z-40">
      <div className="max-w-[1280px] mx-auto h-[72px] px-6 sm:px-10 lg:px-16 flex items-center justify-between gap-3 sm:gap-4">
        {/* Left side: Logo & Nav */}
        <div className="flex items-center gap-6">
          <button
            type="button"
            onClick={() => onSelectRun('')}
            className="flex items-center gap-3 cursor-pointer group bg-transparent border-none p-0 text-left"
            title={t('header_all_runs')}
          >
            {/* Google Style Hollow Circle with Red Dot SVG Logo */}
            <svg width="28" height="28" viewBox="0 0 32 32" fill="none" className="shrink-0 transition-transform group-hover:scale-105">
              <circle cx="16" cy="16" r="12" stroke="var(--accent)" strokeWidth="3" />
              <circle cx="24" cy="8" r="3.5" fill="var(--error)" />
            </svg>
            <span className="text-[22px] font-medium text-[var(--text)] tracking-tight">
              Astra Multi
            </span>
          </button>

          {/* Navigation Pills: Phiên & Cài đặt */}
          <nav className="flex items-center gap-1.5 ml-2" aria-label="Main Navigation">
            <button
              type="button"
              onClick={() => onSelectRun('')}
              className={`h-9 px-4 rounded-full text-[14px] font-medium transition-colors cursor-pointer ${
                !selectedRunId
                  ? 'bg-[var(--accent-tonal)] text-[var(--accent-on-tonal)]'
                  : 'text-[var(--text-2)] hover:bg-[var(--surface-tonal)]'
              }`}
              aria-current={!selectedRunId ? 'page' : undefined}
            >
              {t('header_nav_runs')}
            </button>
            <button
              type="button"
              onClick={onOpenSettings}
              className="h-9 px-4 rounded-full text-[14px] font-medium text-[var(--text-2)] hover:bg-[var(--surface-tonal)] transition-colors cursor-pointer"
            >
              {t('header_btn_settings')}
            </button>
          </nav>
        </div>

        {/* Right side: Status chip, Language, New Run, Logout */}
        <div className="flex items-center gap-3">
          {/* Server status chip */}
          <div
            role="status"
            className={`chip font-medium text-[13px] ${
              isOffline ? 'chip-error' : 'chip-success'
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${
                isOffline ? 'bg-[var(--error)]' : 'bg-[var(--success)]'
              }`}
            />
            <span>
              {isOffline ? t('header_server_disconnected') : t('header_server_connected')}
            </span>
          </div>

          {/* Language Switcher */}
          <LanguageSwitcher />

          {/* New Run Button */}
          <button
            type="button"
            onClick={onOpenNewRun}
            disabled={isOffline}
            className={`h-10 px-5 rounded-full text-[14px] font-medium transition-all ${
              isOffline
                ? 'bg-[var(--surface-tonal)] text-[var(--text-2)] cursor-not-allowed opacity-75'
                : 'bg-[var(--accent)] text-white hover:brightness-95 cursor-pointer shadow-sm'
            }`}
          >
            {t('header_new_run')}
          </button>

          {/* Logout Button */}
          {onLogout && (
            <button
              type="button"
              onClick={onLogout}
              className="w-10 h-10 rounded-full flex items-center justify-center text-[var(--text-2)] hover:bg-[var(--surface-tonal)] transition-colors cursor-pointer"
              title={t('auth_btn_logout')}
              aria-label={t('auth_btn_logout')}
            >
              <LogOut size={16} />
            </button>
          )}
        </div>
      </div>
    </header>
  );
};

export default Header;


