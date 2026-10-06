import React, { useState } from 'react';
import { Lock, ShieldCheck, AlertCircle, Eye, EyeOff } from 'lucide-react';
import { api, ApiError } from '../api';
import { useI18n } from '../i18n';

interface AuthModalProps {
  mode: 'setup' | 'login';
  onAuthenticated: () => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ mode, onAuthenticated }) => {
  const { t } = useI18n();
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (password.length < 4) {
      setError(t('auth_error_too_short'));
      return;
    }

    if (mode === 'setup' && password !== confirmPassword) {
      setError(t('auth_error_mismatch'));
      return;
    }

    try {
      setIsSubmitting(true);
      if (mode === 'setup') {
        await api.setupAdmin(password);
      } else {
        await api.login(password);
      }
      onAuthenticated();
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Authentication failed');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop">
      <div className="modal-container max-w-md" role="dialog" aria-modal="true">
        <div className="modal-header">
          <div className="modal-title-group">
            {mode === 'setup' ? (
              <ShieldCheck className="text-emerald-400" size={22} />
            ) : (
              <Lock className="text-sky-400" size={22} />
            )}
            <h2 className="modal-title">
              {mode === 'setup' ? t('auth_setup_title') : t('auth_login_title')}
            </h2>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="modal-form">
          <p className="text-xs text-slate-400 mb-4 leading-relaxed">
            {mode === 'setup' ? t('auth_setup_subtitle') : t('auth_login_subtitle')}
          </p>

          {error && (
            <div className="error-alert mb-4">
              <AlertCircle size={16} className="flex-shrink-0" />
              <span className="text-xs">{error}</span>
            </div>
          )}

          <div className="form-group mb-4">
            <label className="form-label">
              {t('auth_password_label')} <span className="text-rose-400">*</span>
            </label>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t('auth_password_placeholder')}
                required
                className="form-input w-full pr-10"
                autoFocus
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-2.5 top-2.5 text-slate-400 hover:text-slate-200"
                tabIndex={-1}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {mode === 'setup' && (
            <div className="form-group mb-4">
              <label className="form-label">
                {t('auth_confirm_password_label')} <span className="text-rose-400">*</span>
              </label>
              <input
                type={showPassword ? 'text' : 'password'}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder={t('auth_confirm_password_placeholder')}
                required
                className="form-input w-full"
              />
            </div>
          )}

          <div className="modal-actions mt-4">
            <button
              type="submit"
              disabled={isSubmitting}
              className="btn-primary w-full justify-center py-2"
            >
              {isSubmitting
                ? '...'
                : mode === 'setup'
                ? t('auth_btn_setup')
                : t('auth_btn_login')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
