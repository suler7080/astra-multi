import React, { useState, useEffect } from 'react';
import type { ProviderItem, SaveProviderPayload } from '../types';
import { api, ApiError } from '../api';
import { useI18n } from '../i18n';
import {
  X,
  Settings,
  Cpu,
  Lock,
  Plus,
  Trash2,
  CheckCircle,
  AlertTriangle,
  Play,
  Key,
  Globe,
  Radio,
  Eye,
  EyeOff,
  Edit2,
} from 'lucide-react';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onProviderChanged?: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  onProviderChanged,
}) => {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState<'providers' | 'security'>('providers');
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Provider Form State
  const [isEditing, setIsEditing] = useState(false);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [formName, setFormName] = useState('');
  const [formKind, setFormKind] = useState<'openai' | 'google' | 'openai-compatible'>('openai-compatible');
  const [formBaseUrl, setFormBaseUrl] = useState('');
  const [formModel, setFormModel] = useState('');
  const [formApiKey, setFormApiKey] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [formIsActive, setFormIsActive] = useState(false);

  // Testing State
  const [testingName, setTestingName] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ name: string; success: boolean; latency?: number; error?: string } | null>(null);

  // Password Form State
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmNewPassword, setConfirmNewPassword] = useState('');
  const [isChangingPass, setIsChangingPass] = useState(false);

  useEffect(() => {
    if (isOpen) {
      loadProviders();
      setError(null);
      setSuccessMsg(null);
      setIsEditing(false);
    }
  }, [isOpen]);

  const loadProviders = async () => {
    try {
      setIsLoading(true);
      const data = await api.listProviders();
      setProviders(data);
    } catch (err: unknown) {
      handleError(err, 'Failed to load provider settings');
    } finally {
      setIsLoading(false);
    }
  };

  const handleError = (err: unknown, fallback: string) => {
    if (err instanceof ApiError) {
      setError(err.message);
    } else if (err instanceof Error) {
      setError(err.message);
    } else {
      setError(fallback);
    }
  };

  const handleStartAdd = () => {
    setEditingName(null);
    setFormName('');
    setFormKind('openai-compatible');
    setFormBaseUrl('https://api.xkiro.com/v1');
    setFormModel('qwen/qwen3.7-flash:free');
    setFormApiKey('');
    setFormIsActive(false);
    setIsEditing(true);
    setTestResult(null);
    setError(null);
  };

  const handleStartEdit = (p: ProviderItem) => {
    setEditingName(p.name);
    setFormName(p.name);
    setFormKind(p.kind);
    setFormBaseUrl(p.base_url || '');
    setFormModel(p.model);
    setFormApiKey('');
    setFormIsActive(p.is_active);
    setIsEditing(true);
    setTestResult(null);
    setError(null);
  };

  const handleSaveProvider = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const payload: SaveProviderPayload = {
      name: formName.trim().toLowerCase(),
      kind: formKind,
      model: formModel.trim(),
      base_url: formBaseUrl.trim() || null,
      api_key: formApiKey.trim() || undefined,
      is_active: formIsActive,
    };

    try {
      setIsLoading(true);
      await api.saveProvider(payload);
      setIsEditing(false);
      await loadProviders();
      setSuccessMsg(`Provider ${payload.name} saved successfully.`);
      setTimeout(() => setSuccessMsg(null), 4000);
      if (payload.is_active && onProviderChanged) {
        onProviderChanged();
      }
    } catch (err: unknown) {
      handleError(err, 'Failed to save provider');
    } finally {
      setIsLoading(false);
    }
  };

  const handleActivate = async (name: string) => {
    try {
      setIsLoading(true);
      await api.activateProvider(name);
      await loadProviders();
      setSuccessMsg(`Active provider switched to ${name}`);
      setTimeout(() => setSuccessMsg(null), 4000);
      if (onProviderChanged) {
        onProviderChanged();
      }
    } catch (err: unknown) {
      handleError(err, 'Failed to activate provider');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (name: string) => {
    if (!window.confirm(`Delete provider profile "${name}"?`)) return;
    try {
      setIsLoading(true);
      await api.deleteProvider(name);
      await loadProviders();
    } catch (err: unknown) {
      handleError(err, 'Failed to delete provider');
    } finally {
      setIsLoading(false);
    }
  };

  const handleTestConnection = async (p?: ProviderItem) => {
    const targetName = p ? p.name : formName;
    setTestingName(targetName);
    setTestResult(null);
    try {
      const res = await api.testProvider({
        name: p ? p.name : (editingName || undefined),
        kind: p ? p.kind : formKind,
        base_url: p ? p.base_url : (formBaseUrl.trim() || null),
        model: p ? p.model : formModel.trim(),
        api_key: p ? undefined : (formApiKey.trim() || undefined),
      });
      setTestResult({
        name: targetName,
        success: res.success,
        latency: res.latency_ms,
        error: res.error,
      });
    } catch (err: unknown) {
      setTestResult({
        name: targetName,
        success: false,
        error: err instanceof Error ? err.message : 'Connection probe failed',
      });
    } finally {
      setTestingName(null);
    }
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccessMsg(null);

    if (newPassword.length < 4) {
      setError(t('auth_error_too_short'));
      return;
    }

    if (newPassword !== confirmNewPassword) {
      setError(t('auth_error_mismatch'));
      return;
    }

    try {
      setIsChangingPass(true);
      await api.changePassword(currentPassword, newPassword);
      setSuccessMsg(t('settings_password_updated'));
      setCurrentPassword('');
      setNewPassword('');
      setConfirmNewPassword('');
    } catch (err: unknown) {
      handleError(err, 'Failed to update password');
    } finally {
      setIsChangingPass(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop">
      <div className="modal-container max-w-2xl" role="dialog" aria-modal="true">
        <div className="modal-header">
          <div className="modal-title-group">
            <Settings className="text-sky-400" size={20} />
            <h2 className="modal-title">{t('settings_title')}</h2>
          </div>
          <button onClick={onClose} className="btn-icon" aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        {/* Tab Header */}
        <div className="flex border-b border-slate-800 px-6 pt-3 gap-4">
          <button
            onClick={() => { setActiveTab('providers'); setError(null); }}
            className={`pb-3 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all ${
              activeTab === 'providers'
                ? 'border-sky-400 text-sky-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Cpu size={15} />
            <span>{t('settings_tab_providers')}</span>
          </button>
          <button
            onClick={() => { setActiveTab('security'); setError(null); }}
            className={`pb-3 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all ${
              activeTab === 'security'
                ? 'border-sky-400 text-sky-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Lock size={15} />
            <span>{t('settings_tab_security')}</span>
          </button>
        </div>

        <div className="p-6">
          {error && (
            <div className="error-alert mb-4">
              <AlertTriangle size={16} className="flex-shrink-0" />
              <span className="text-xs">{error}</span>
            </div>
          )}

          {successMsg && (
            <div className="p-3 mb-4 rounded bg-emerald-950/40 border border-emerald-800 text-emerald-300 text-xs flex items-center gap-2">
              <CheckCircle size={16} className="text-emerald-400" />
              <span>{successMsg}</span>
            </div>
          )}

          {/* TAB 1: LLM PROVIDERS */}
          {activeTab === 'providers' && (
            <div>
              {!isEditing ? (
                <>
                  <div className="flex justify-between items-center mb-4">
                    <span className="text-xs text-slate-400">
                      Configure LLM API keys and model profiles for autonomous multi-agent planning.
                    </span>
                    <button onClick={handleStartAdd} className="btn-primary text-xs py-1.5 px-3 flex items-center gap-1.5">
                      <Plus size={14} />
                      <span>{t('settings_add_provider')}</span>
                    </button>
                  </div>

                  <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
                    {providers.map((p) => {
                      const isCurrentTest = testResult && testResult.name === p.name;
                      return (
                        <div
                          key={p.name}
                          className={`p-4 rounded-lg border transition-all ${
                            p.is_active
                              ? 'bg-slate-900/90 border-sky-500/70 shadow-lg shadow-sky-950/20'
                              : 'bg-slate-900/40 border-slate-800 hover:border-slate-700'
                          }`}
                        >
                          <div className="flex items-start justify-between">
                            <div>
                              <div className="flex items-center gap-2 mb-1">
                                <span className="font-semibold text-sm text-slate-100 font-mono">{p.name}</span>
                                <span className="badge-subtle text-[11px] uppercase">{p.kind}</span>
                                {p.is_active && (
                                  <span className="badge-emerald text-[10px] flex items-center gap-1 font-semibold">
                                    <Radio size={10} className="animate-pulse" />
                                    {t('settings_active_badge')}
                                  </span>
                                )}
                              </div>
                              <p className="text-xs text-sky-300 font-mono mb-1">{p.model}</p>
                              {p.base_url && (
                                <p className="text-[11px] text-slate-400 flex items-center gap-1 font-mono truncate max-w-md">
                                  <Globe size={11} /> {p.base_url}
                                </p>
                              )}
                              <p className="text-[11px] text-slate-400 mt-1 flex items-center gap-1">
                                <Key size={11} className={p.has_api_key ? 'text-emerald-400' : 'text-slate-500'} />
                                <span>{p.has_api_key ? 'API Key Encrypted & Stored' : 'No API Key Configured'}</span>
                              </p>
                            </div>

                            <div className="flex items-center gap-2">
                              {!p.is_active && (
                                <button
                                  onClick={() => handleActivate(p.name)}
                                  className="btn-secondary text-xs py-1 px-2.5"
                                  title="Activate"
                                >
                                  {t('settings_btn_activate')}
                                </button>
                              )}
                              <button
                                onClick={() => handleTestConnection(p)}
                                disabled={testingName === p.name}
                                className="btn-secondary text-xs py-1 px-2.5 flex items-center gap-1"
                                title="Probe Connection"
                              >
                                <Play size={11} className={testingName === p.name ? 'animate-spin text-sky-400' : ''} />
                                <span>{testingName === p.name ? t('settings_btn_testing') : t('settings_btn_test')}</span>
                              </button>
                              <button
                                onClick={() => handleStartEdit(p)}
                                className="btn-icon p-1.5"
                                title="Edit"
                              >
                                <Edit2 size={13} />
                              </button>
                              {!p.is_active && (
                                <button
                                  onClick={() => handleDelete(p.name)}
                                  className="btn-icon-danger p-1.5"
                                  title="Delete"
                                >
                                  <Trash2 size={13} />
                                </button>
                              )}
                            </div>
                          </div>

                          {/* Test connection result banner */}
                          {isCurrentTest && (
                            <div className={`mt-3 p-2 rounded text-xs flex items-center gap-2 ${
                              testResult.success
                                ? 'bg-emerald-950/30 border border-emerald-900/60 text-emerald-300'
                                : 'bg-rose-950/30 border border-rose-900/60 text-rose-300'
                            }`}>
                              {testResult.success ? (
                                <>
                                  <CheckCircle size={14} className="text-emerald-400 flex-shrink-0" />
                                  <span>{t('settings_test_success')} ({testResult.latency} ms)</span>
                                </>
                              ) : (
                                <>
                                  <AlertTriangle size={14} className="text-rose-400 flex-shrink-0" />
                                  <span className="truncate">{t('settings_test_failed')}: {testResult.error}</span>
                                </>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </>
              ) : (
                /* Edit / Add Provider Form */
                <form onSubmit={handleSaveProvider} className="space-y-4">
                  <div className="flex justify-between items-center border-b border-slate-800 pb-2">
                    <h3 className="text-sm font-semibold text-slate-200">
                      {editingName ? t('settings_edit_provider') : t('settings_add_provider')}
                    </h3>
                    <button
                      type="button"
                      onClick={() => setIsEditing(false)}
                      className="btn-text-sm"
                    >
                      Cancel
                    </button>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="form-group">
                      <label className="form-label">{t('settings_provider_name')} *</label>
                      <input
                        type="text"
                        value={formName}
                        onChange={(e) => setFormName(e.target.value)}
                        placeholder="e.g. xkiro, my-ollama, openrouter"
                        required
                        disabled={Boolean(editingName)}
                        className="form-input"
                      />
                    </div>

                    <div className="form-group">
                      <label className="form-label">{t('settings_provider_kind')} *</label>
                      <select
                        value={formKind}
                        onChange={(e) => setFormKind(e.target.value as any)}
                        className="form-select"
                      >
                        <option value="openai-compatible">OpenAI-Compatible (Xkiro, Ollama, vLLM, OpenRouter)</option>
                        <option value="openai">OpenAI Official</option>
                        <option value="google">Google Gemini</option>
                      </select>
                    </div>
                  </div>

                  <div className="form-group">
                    <label className="form-label">{t('settings_model')} *</label>
                    <input
                      type="text"
                      value={formModel}
                      onChange={(e) => setFormModel(e.target.value)}
                      placeholder="e.g. qwen/qwen3.7-flash:free, gpt-4o-mini, gemini-2.0-flash"
                      required
                      className="form-input"
                    />
                  </div>

                  <div className="form-group">
                    <label className="form-label">{t('settings_base_url')}</label>
                    <input
                      type="text"
                      value={formBaseUrl}
                      onChange={(e) => setFormBaseUrl(e.target.value)}
                      placeholder="e.g. https://api.xkiro.com/v1"
                      className="form-input"
                    />
                  </div>

                  <div className="form-group">
                    <label className="form-label">{t('settings_api_key')}</label>
                    <div className="relative">
                      <input
                        type={showApiKey ? 'text' : 'password'}
                        value={formApiKey}
                        onChange={(e) => setFormApiKey(e.target.value)}
                        placeholder={editingName ? t('settings_api_key_placeholder') : 'sk-xt-...'}
                        className="form-input w-full pr-10"
                      />
                      <button
                        type="button"
                        onClick={() => setShowApiKey(!showApiKey)}
                        className="absolute right-2.5 top-2.5 text-slate-400 hover:text-slate-200"
                        tabIndex={-1}
                      >
                        {showApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
                      </button>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={formIsActive}
                        onChange={(e) => setFormIsActive(e.target.checked)}
                        className="rounded bg-slate-800 border-slate-700"
                      />
                      <span>{t('settings_btn_activate')}</span>
                    </label>
                  </div>

                  {testResult && (
                    <div className={`p-2.5 rounded text-xs flex items-center gap-2 ${
                      testResult.success
                        ? 'bg-emerald-950/30 border border-emerald-900 text-emerald-300'
                        : 'bg-rose-950/30 border border-rose-900 text-rose-300'
                    }`}>
                      {testResult.success ? (
                        <>
                          <CheckCircle size={14} className="text-emerald-400" />
                          <span>{t('settings_test_success')} ({testResult.latency} ms)</span>
                        </>
                      ) : (
                        <>
                          <AlertTriangle size={14} className="text-rose-400" />
                          <span>{t('settings_test_failed')}: {testResult.error}</span>
                        </>
                      )}
                    </div>
                  )}

                  <div className="modal-actions pt-2">
                    <button
                      type="button"
                      onClick={() => handleTestConnection()}
                      disabled={Boolean(testingName)}
                      className="btn-secondary text-xs"
                    >
                      {testingName ? t('settings_btn_testing') : t('settings_btn_test')}
                    </button>
                    <button
                      type="submit"
                      disabled={isLoading}
                      className="btn-primary text-xs"
                    >
                      {isLoading ? '...' : t('settings_btn_save')}
                    </button>
                  </div>
                </form>
              )}
            </div>
          )}

          {/* TAB 2: ADMIN SECURITY */}
          {activeTab === 'security' && (
            <form onSubmit={handleChangePassword} className="space-y-4 max-w-md">
              <p className="text-xs text-slate-400">
                Update your administrator password to maintain strong access control.
              </p>

              <div className="form-group">
                <label className="form-label">{t('settings_current_password')} *</label>
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  required
                  className="form-input"
                />
              </div>

              <div className="form-group">
                <label className="form-label">{t('settings_new_password')} *</label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder={t('auth_password_placeholder')}
                  required
                  className="form-input"
                />
              </div>

              <div className="form-group">
                <label className="form-label">{t('auth_confirm_password_label')} *</label>
                <input
                  type="password"
                  value={confirmNewPassword}
                  onChange={(e) => setConfirmNewPassword(e.target.value)}
                  required
                  className="form-input"
                />
              </div>

              <div className="pt-2">
                <button
                  type="submit"
                  disabled={isChangingPass}
                  className="btn-primary text-xs"
                >
                  {isChangingPass ? '...' : t('settings_btn_change_password')}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};
