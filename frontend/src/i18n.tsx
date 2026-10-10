import React, { useState } from 'react';
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
    <div className={`lang-switcher-container ${className}`}>
      <button
        type="button"
        onClick={() => setLang('EN')}
        className={`lang-btn ${lang === 'EN' ? 'lang-btn-active' : ''}`}
        title="Switch to English"
      >
        <span className="lang-flag">🇬🇧</span>
        <span>ENG</span>
      </button>
      <button
        type="button"
        onClick={() => setLang('VN')}
        className={`lang-btn ${lang === 'VN' ? 'lang-btn-active' : ''}`}
        title="Chuyển sang Tiếng Việt"
      >
        <span className="lang-flag">🇻🇳</span>
        <span>VN</span>
      </button>
    </div>
  );
};
