import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import {
  type Language,
  translations,
  type TranslationKey,
  I18nContext,
  useI18n,
} from './i18nContext';

export const I18nProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [lang, setLangState] = useState<Language>(() => {
    const saved = localStorage.getItem('astra_lang');
    return saved === 'EN' || saved === 'VN' ? saved : 'VN';
  });

  const setLang = (newLang: Language) => {
    setLangState(newLang);
    localStorage.setItem('astra_lang', newLang);
  };

  const t = (key: TranslationKey, fallback?: string): string => {
    const currentDict = translations[lang];
    if (key in currentDict) {
      return currentDict[key];
    }
    return fallback || key;
  };

  return (
    <I18nContext.Provider value={{ lang, setLang, t }}>
      {children}
    </I18nContext.Provider>
  );
};

export const LanguageSwitcher: React.FC<{ className?: string }> = ({ className = '' }) => {
  const { lang, setLang } = useI18n();

  return (
    <button
      type="button"
      onClick={() => setLang(lang === 'VN' ? 'EN' : 'VN')}
      className={`inline-flex items-center gap-1.5 px-4 h-10 rounded-full border border-[var(--border-strong)] text-[14px] font-medium text-[var(--text)] bg-[var(--bg)] hover:bg-[var(--surface-tonal)] transition-colors cursor-pointer select-none ${className}`}
      title={lang === 'VN' ? 'Switch to English' : 'Chuyển sang Tiếng Việt'}
    >
      <span>{lang === 'VN' ? 'Tiếng Việt' : 'English'}</span>
      <ChevronDown size={14} className="text-[var(--text-2)]" />
    </button>
  );
};
