import React, { useState, useEffect, useCallback, useRef } from 'react';
import type { ProviderItem, SaveProviderPayload, RoleMappings, RoleMappingsResponse } from '../types';
import { api, ApiError, classifyApiError, type ClassifiedError } from '../api';
import { useI18n } from '../i18nContext';
import { ConfirmModal } from './ConfirmModal';
import {
  X,
  Settings,
  Cpu,
  Lock,
  Users,
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
  Compass,
  ShieldAlert,
  GitMerge,
  Info,
  RefreshCw,
} from 'lucide-react';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onProviderChanged?: () => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = React.memo(({
  isOpen,
  onClose,
  onProviderChanged,
}) => {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState<'providers' | 'roles' | 'security'>('providers');
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [loadProviderError, setLoadProviderError] = useState<ClassifiedError | null>(null);

  // Scroll indicators state & ref
  const bodyRef = useRef<HTMLDivElement>(null);
  const [canScrollUp, setCanScrollUp] = useState(false);
  const [canScrollDown, setCanScrollDown] = useState(false);

  // Focus restoration & Escape listener & scroll lock
  const previousActiveElementRef = useRef<HTMLElement | null>(null);

  // Role Mappings State
  const [roleMappings, setRoleMappings] = useState<RoleMappings>({
    planner: null,
    reviewer: null,
    synthesizer: null,
  });
  const [activeProviderName, setActiveProviderName] = useState<string>('');
  const [isSavingRoles, setIsSavingRoles] = useState(false);

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
  const [deletingProviderName, setDeletingProviderName] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{
    name: string;
    success: boolean;
    latency?: number;
    error?: string;
  } | null>(null);

  // Password Form State
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmNewPassword, setConfirmNewPassword] = useState('');
  const [isChangingPass, setIsChangingPass] = useState(false);
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmNewPassword, setShowConfirmNewPassword] = useState(false);

  // Model Discovery & Switching State
  const [providerModelsCache, setProviderModelsCache] = useState<Record<string, string[]>>({});
  const providerModelsCacheRef = useRef<Record<string, string[]>>({});
  const [loadingModels, setLoadingModels] = useState<Record<string, boolean>>({});
  const [customModelMode, setCustomModelMode] = useState<Record<string, boolean>>({});
  const [scanningFormModels, setScanningFormModels] = useState(false);
  const [formDiscoveredModels, setFormDiscoveredModels] = useState<string[]>([]);
  const [customFormModelMode, setCustomFormModelMode] = useState(false);
  const [roleApiKeyInputs, setRoleApiKeyInputs] = useState<Record<string, string>>({});
  const [showRoleApiKey, setShowRoleApiKey] = useState<Record<string, boolean>>({});

  const handleError = useCallback((err: unknown, fallback: string) => {
    if (err instanceof ApiError) {
      setError(err.message);
    } else if (err instanceof Error) {
      setError(err.message);
    } else {
      setError(fallback);
    }
  }, []);

  const fetchModelsForProvider = useCallback(async (providerName: string, force = false) => {
    if (!providerName) return;
    if (!force && providerModelsCacheRef.current[providerName]?.length) return;
    setLoadingModels((prev) => ({ ...prev, [providerName]: true }));
    try {
      const models = await api.getProviderModels(providerName);
      providerModelsCacheRef.current[providerName] = models;
      setProviderModelsCache((prev) => ({ ...prev, [providerName]: models }));
    } catch (err: unknown) {
      console.warn(`Could not load models for ${providerName}:`, err);
    } finally {
      setLoadingModels((prev) => ({ ...prev, [providerName]: false }));
    }
  }, []);

  const checkScroll = useCallback(() => {
    const el = bodyRef.current;
    if (!el) return;
    const hasScrollable = el.scrollHeight > el.clientHeight;
    setCanScrollUp(hasScrollable && el.scrollTop > 5);
    setCanScrollDown(hasScrollable && el.scrollTop + el.clientHeight < el.scrollHeight - 5);
  }, []);

  useEffect(() => {
    if (isOpen) {
      const timer = setTimeout(checkScroll, 60);
      return () => clearTimeout(timer);
    }
  }, [isOpen, activeTab, providers, isEditing, loadProviderError, checkScroll]);

  useEffect(() => {
    if (isOpen) {
      previousActiveElementRef.current = document.activeElement as HTMLElement | null;
      const originalOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';

      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === 'Escape') {
          onClose();
        }
      };

      window.addEventListener('keydown', handleKeyDown);

      return () => {
        document.body.style.overflow = originalOverflow;
        window.removeEventListener('keydown', handleKeyDown);
        previousActiveElementRef.current?.focus();
      };
    }
  }, [isOpen, onClose]);

  const loadProviders = useCallback(async () => {
    try {
      setIsLoading(true);
      setLoadProviderError(null);
      const data = await api.listProviders();
      setProviders(data);
    } catch (err: unknown) {
      setLoadProviderError(classifyApiError(err));
    } finally {
      setIsLoading(false);
    }
  }, []);

  const extractRoleMappings = (res: RoleMappingsResponse): RoleMappings => ({
    planner: res.planner ?? res.mappings?.planner ?? null,
    reviewer: res.reviewer ?? res.mappings?.reviewer ?? null,
    synthesizer: res.synthesizer ?? res.mappings?.synthesizer ?? null,
  });

  const loadRoleMappings = useCallback(async () => {
    try {
      const res = await api.getRoleMappings();
      const extracted = extractRoleMappings(res);
      setRoleMappings(extracted);
      const activeName = res.active_provider || '';
      setActiveProviderName(activeName);

      const toFetch = new Set<string>();
      if (activeName) toFetch.add(activeName);
      if (extracted.planner?.provider) toFetch.add(extracted.planner.provider);
      if (extracted.reviewer?.provider) toFetch.add(extracted.reviewer.provider);
      if (extracted.synthesizer?.provider) toFetch.add(extracted.synthesizer.provider);
      for (const p of toFetch) {
        void fetchModelsForProvider(p);
      }
    } catch (err: unknown) {
      handleError(err, 'Failed to load role assignments');
    }
  }, [handleError, fetchModelsForProvider]);

  const hasInitializedOpenRef = useRef(false);

  useEffect(() => {
    if (!isOpen) {
      hasInitializedOpenRef.current = false;
      return;
    }
    if (hasInitializedOpenRef.current) return;
    hasInitializedOpenRef.current = true;

    let ignore = false;
    api.listProviders()
      .then((data) => {
        if (!ignore) {
          setProviders(data);
          setLoadProviderError(null);
        }
      })
      .catch((err: unknown) => {
        if (!ignore) {
          setLoadProviderError(classifyApiError(err));
        }
      });

    void loadRoleMappings();

    return () => {
      ignore = true;
    };
  }, [isOpen, loadRoleMappings]);

  const handleRoleProviderChange = (
    roleKey: 'planner' | 'reviewer' | 'synthesizer',
    providerName: string
  ) => {
    setRoleMappings((prev) => {
      if (!providerName) {
        return {
          ...prev,
          [roleKey]: null,
        };
      }
      return {
        ...prev,
        [roleKey]: {
          provider: providerName,
          model: prev[roleKey]?.provider === providerName ? prev[roleKey]?.model : '',
          has_custom_key: prev[roleKey]?.provider === providerName ? prev[roleKey]?.has_custom_key : false,
        },
      };
    });
    setRoleApiKeyInputs((prev) => {
      const copy = { ...prev };
      delete copy[roleKey];
      return copy;
    });
    if (providerName) {
      void fetchModelsForProvider(providerName);
    }
  };

  const handleRoleModelChange = (
    roleKey: 'planner' | 'reviewer' | 'synthesizer',
    modelName: string
  ) => {
    setRoleMappings((prev) => {
      const currentProvider = prev[roleKey]?.provider || activeProviderName;
      return {
        ...prev,
        [roleKey]: {
          provider: currentProvider,
          model: modelName,
          has_custom_key: prev[roleKey]?.has_custom_key,
        },
      };
    });
  };

  const handleScanFormModels = async () => {
    try {
      setScanningFormModels(true);
      setError(null);
      const models = await api.discoverModels({
        name: editingName || formName || undefined,
        kind: formKind,
        base_url: formBaseUrl || undefined,
        api_key: formApiKey || undefined,
      });
      setFormDiscoveredModels(models);
      if (models.length > 0 && !formModel) {
        setFormModel(models[0]);
      }
      setSuccessMsg(t('settings_models_count').replace('{count}', String(models.length)));
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: unknown) {
      handleError(err, 'Failed to scan models from provider.');
    } finally {
      setScanningFormModels(false);
    }
  };

  const handleSaveRoleMappings = async () => {
    setError(null);
    setSuccessMsg(null);
    try {
      setIsSavingRoles(true);
      const payload: RoleMappings = {
        planner: roleMappings.planner?.provider ? {
          provider: roleMappings.planner.provider,
          model: roleMappings.planner.model?.trim() || null,
          api_key: roleApiKeyInputs.planner !== undefined ? roleApiKeyInputs.planner : undefined,
        } : null,
        reviewer: roleMappings.reviewer?.provider ? {
          provider: roleMappings.reviewer.provider,
          model: roleMappings.reviewer.model?.trim() || null,
          api_key: roleApiKeyInputs.reviewer !== undefined ? roleApiKeyInputs.reviewer : undefined,
        } : null,
        synthesizer: roleMappings.synthesizer?.provider ? {
          provider: roleMappings.synthesizer.provider,
          model: roleMappings.synthesizer.model?.trim() || null,
          api_key: roleApiKeyInputs.synthesizer !== undefined ? roleApiKeyInputs.synthesizer : undefined,
        } : null,
      };
      const res = await api.saveRoleMappings(payload);
      setRoleMappings(extractRoleMappings(res));
      setRoleApiKeyInputs({});
      setActiveProviderName(res.active_provider || '');
      setSuccessMsg(t('role_save_success'));
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: unknown) {
      handleError(err, 'Failed to save role assignments');
    } finally {
      setIsSavingRoles(false);
    }
  };

  const applyPreset = (
    name: string,
    kind: 'openai' | 'google' | 'openai-compatible',
    url: string,
    defaultModel: string
  ) => {
    setFormName(name);
    setFormKind(kind);
    setFormBaseUrl(url);
    setFormModel(defaultModel);
    setFormDiscoveredModels([]);
    setCustomFormModelMode(false);
  };

  const handleStartAdd = () => {
    setEditingName(null);
    setFormName('tokenharbor');
    setFormKind('openai-compatible');
    setFormBaseUrl('https://tokenharbor.ai/v1');
    setFormModel('gpt-4o-mini');
    setFormApiKey('');
    setFormIsActive(false);
    setFormDiscoveredModels([]);
    setCustomFormModelMode(false);
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
    setFormDiscoveredModels([]);
    setCustomFormModelMode(false);
    setIsEditing(true);
    setTestResult(null);
    setError(null);
    if (p.has_api_key) {
      void api.getProviderModels(p.name).then((models) => {
        setFormDiscoveredModels(models);
      }).catch(() => {});
    }
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

  const handleConfirmDelete = async () => {
    if (!deletingProviderName) return;
    const target = deletingProviderName;
    try {
      setIsLoading(true);
      await api.deleteProvider(target);
      await loadProviders();
      setDeletingProviderName(null);
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
      if (
        (err instanceof ApiError && (err.status === 400 && err.message.toLowerCase().includes('current password is incorrect'))) ||
        (err instanceof Error && err.message.toLowerCase().includes('current password is incorrect'))
      ) {
        setError(t('settings_current_password_error'));
      } else {
        handleError(err, t('err_change_password'));
      }
    } finally {
      setIsChangingPass(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div className="modal-container modal-container-settings" role="dialog" aria-modal="true">
        <div className="modal-header">
          <div className="modal-title-group">
            <Settings className="text-[#1967D2]" size={20} />
            <h2 className="modal-title">{t('settings_title')}</h2>
          </div>
          <button onClick={onClose} className="btn-icon" aria-label={t('btn_close_modal')}>
            <X size={18} />
          </button>
        </div>

        {/* Tab Header */}
        <div className="settings-modal-tabs">
          <button
            onClick={() => { setActiveTab('providers'); setError(null); }}
            className={`settings-tab-btn ${activeTab === 'providers' ? 'settings-tab-btn-active' : ''}`}
          >
            <Cpu size={15} />
            <span>{t('settings_tab_providers')}</span>
          </button>
          <button
            onClick={() => { setActiveTab('roles'); setError(null); }}
            className={`settings-tab-btn ${activeTab === 'roles' ? 'settings-tab-btn-active' : ''}`}
          >
            <Users size={15} />
            <span>{t('settings_tab_roles')}</span>
          </button>
          <button
            onClick={() => { setActiveTab('security'); setError(null); }}
            className={`settings-tab-btn ${activeTab === 'security' ? 'settings-tab-btn-active' : ''}`}
          >
            <Lock size={15} />
            <span>{t('settings_tab_security')}</span>
          </button>
        </div>

        <div className={`settings-body-wrapper ${canScrollUp ? 'has-scroll-up' : ''} ${canScrollDown ? 'has-scroll-down' : ''}`}>
          <div ref={bodyRef} onScroll={checkScroll} className="settings-body">
            {error && (
              <div className="error-alert mb-4">
                <AlertTriangle size={16} className="flex-shrink-0" />
                <span className="text-xs">{error}</span>
              </div>
            )}

            {successMsg && (
              <div className="test-banner-success mb-4">
                <CheckCircle size={16} />
                <span>{successMsg}</span>
              </div>
            )}

            {/* TAB 1: LLM PROVIDERS */}
            {activeTab === 'providers' && (
              <div>
                {!isEditing ? (
                  <>
                    <div className="settings-section-header">
                      <span className="text-xs text-[#5F6368]">
                        {t('settings_providers_desc')}
                      </span>
                      <button onClick={handleStartAdd} className="btn-primary btn-sm flex items-center gap-1.5">
                        <Plus size={14} />
                        <span>{t('settings_add_provider')}</span>
                      </button>
                    </div>

                    {loadProviderError ? (
                      <div className="settings-error-card">
                        <div className="settings-error-content">
                          <AlertTriangle size={20} className="text-amber-400 flex-shrink-0 mt-0.5" />
                          <div>
                            <div className="settings-error-title">{t('err_load_providers')}</div>
                            <div className="settings-error-desc">
                              {loadProviderError.category === 'backend_offline'
                                ? t('settings_provider_offline_desc')
                                : (loadProviderError.userMessage || t('settings_provider_offline_desc'))}
                            </div>
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => void loadProviders()}
                          disabled={isLoading}
                          className="btn-secondary btn-sm flex items-center gap-1.5 flex-shrink-0"
                        >
                          <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} />
                          <span>{t('conn_retry')}</span>
                        </button>
                      </div>
                    ) : providers.length === 0 ? (
                      <div className="settings-empty-providers">
                        <div className="empty-provider-icon">
                          <Cpu size={26} className="text-[#1967D2]" />
                        </div>
                        <h4 className="empty-provider-title">{t('settings_no_providers_title')}</h4>
                        <p className="empty-provider-desc">{t('settings_no_providers_desc')}</p>
                        <button
                          type="button"
                          onClick={handleStartAdd}
                          className="btn-primary btn-sm flex items-center gap-1.5"
                        >
                          <Plus size={14} />
                          <span>{t('settings_add_provider')}</span>
                        </button>
                      </div>
                    ) : (
                      <div className="provider-card-list">
                        {providers.map((p) => {
                          const isCurrentTest = testResult && testResult.name === p.name;
                          return (
                            <div
                              key={p.name}
                              className={`provider-card ${p.is_active ? 'provider-card-active' : ''}`}
                            >
                              <div className="provider-card-header">
                                <div className="provider-info">
                                  <div className="provider-badges">
                                    <span className="provider-name">{p.name}</span>
                                    <span className="badge-subtle uppercase text-[10px]">{p.kind}</span>
                                    {p.is_active && (
                                      <span className="badge-emerald text-[10px] flex items-center gap-1 font-semibold">
                                        <Radio size={10} className="animate-pulse" />
                                        {t('settings_active_badge')}
                                      </span>
                                    )}
                                  </div>
                                  <div className="provider-model-name">{p.model}</div>
                                  {p.base_url && (
                                    <div className="provider-meta-row">
                                      <Globe size={12} />
                                      <span>{p.base_url}</span>
                                    </div>
                                  )}
                                  <div className="provider-meta-row mt-1">
                                    <Key size={12} className={p.has_api_key ? 'text-[#1E8E3E]' : 'text-[#9AA0A6]'} />
                                    <span className="text-[#5F6368]">{p.has_api_key ? t('settings_key_stored') : t('settings_key_missing')}</span>
                                  </div>
                                </div>

                                <div className="provider-actions-row">
                                  {!p.is_active && (
                                    <button
                                      onClick={() => handleActivate(p.name)}
                                      className="btn-secondary btn-sm"
                                      title={t('settings_action_activate')}
                                    >
                                      {t('settings_btn_activate')}
                                    </button>
                                  )}
                                  <button
                                    onClick={() => handleTestConnection(p)}
                                    disabled={testingName === p.name}
                                    className="btn-secondary btn-sm flex items-center gap-1"
                                    title={t('settings_action_probe')}
                                  >
                                    <Play size={11} className={testingName === p.name ? 'animate-spin text-[#1967D2]' : ''} />
                                    <span>{testingName === p.name ? t('settings_btn_testing') : t('settings_btn_test')}</span>
                                  </button>
                                  <button
                                    onClick={() => handleStartEdit(p)}
                                    className="btn-icon p-1.5 rounded-full hover:bg-[var(--surface-tonal)] text-[var(--text-2)] hover:text-[var(--text)] transition-colors"
                                    title={t('settings_action_edit')}
                                  >
                                    <Edit2 size={13} />
                                  </button>
                                  {!p.is_active && (
                                    <button
                                      onClick={() => setDeletingProviderName(p.name)}
                                      className="btn-icon-danger p-1.5 rounded-full hover:bg-[var(--error-tonal)] text-[var(--text-2)] hover:text-[var(--error)] transition-colors"
                                      title={t('settings_action_delete')}
                                    >
                                      <Trash2 size={13} />
                                    </button>
                                  )}
                                </div>
                              </div>

                              {/* Test connection result banner */}
                              {isCurrentTest && (
                                <div className={testResult.success ? 'test-banner-success' : 'test-banner-error'}>
                                  {testResult.success ? (
                                    <>
                                      <CheckCircle size={14} className="flex-shrink-0" />
                                      <span>{t('settings_test_success')} ({testResult.latency} ms)</span>
                                    </>
                                  ) : (
                                    <>
                                      <AlertTriangle size={14} className="flex-shrink-0" />
                                      <span>{t('settings_test_failed')}: {testResult.error}</span>
                                    </>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </>
                ) : (
                  /* Edit / Add Provider Form */
                  <form onSubmit={handleSaveProvider} className="space-y-4">
                    <div className="flex justify-between items-center border-b border-[#E8EAED] pb-2 mb-3">
                      <h3 className="text-sm font-semibold text-[#202124]">
                        {editingName ? t('settings_edit_provider') : t('settings_add_provider')}
                      </h3>
                      <button
                        type="button"
                        onClick={() => setIsEditing(false)}
                        className="btn-text-sm"
                      >
                        {t('modal_btn_cancel')}
                      </button>
                    </div>

                    {!editingName && (
                      <div className="flex items-center gap-1.5 flex-wrap pb-1 mb-2">
                        <span className="text-[11px] text-[#5F6368] font-medium mr-1">{t('settings_preset_label')}</span>
                        <button
                          type="button"
                          onClick={() => applyPreset('tokenharbor', 'openai-compatible', 'https://tokenharbor.ai/v1', 'gpt-4o-mini')}
                          className={`text-[11px] px-2.5 py-0.5 rounded-full border transition-colors cursor-pointer ${
                            formName === 'tokenharbor'
                              ? 'bg-[#E8F0FE] text-[#1967D2] border-[#1967D2]/40 font-semibold'
                              : 'bg-[#F8F9FA] text-[#3C4043] border-[#DADCE0] hover:bg-[#F1F3F4]'
                          }`}
                        >
                          TokenHarbor
                        </button>
                        <button
                          type="button"
                          onClick={() => applyPreset('xkiro', 'openai-compatible', 'https://api.xkiro.com/v1', 'qwen/qwen3.7-flash:free')}
                          className={`text-[11px] px-2.5 py-0.5 rounded-full border transition-colors cursor-pointer ${
                            formName === 'xkiro'
                              ? 'bg-[#E8F0FE] text-[#1967D2] border-[#1967D2]/40 font-semibold'
                              : 'bg-[#F8F9FA] text-[#3C4043] border-[#DADCE0] hover:bg-[#F1F3F4]'
                          }`}
                        >
                          xKiro
                        </button>
                        <button
                          type="button"
                          onClick={() => applyPreset('openrouter', 'openai-compatible', 'https://openrouter.ai/api/v1', 'openai/gpt-4o-mini')}
                          className={`text-[11px] px-2.5 py-0.5 rounded-full border transition-colors cursor-pointer ${
                            formName === 'openrouter'
                              ? 'bg-[#E8F0FE] text-[#1967D2] border-[#1967D2]/40 font-semibold'
                              : 'bg-[#F8F9FA] text-[#3C4043] border-[#DADCE0] hover:bg-[#F1F3F4]'
                          }`}
                        >
                          OpenRouter
                        </button>
                        <button
                          type="button"
                          onClick={() => applyPreset('openai', 'openai', 'https://api.openai.com/v1', 'gpt-4o-mini')}
                          className={`text-[11px] px-2.5 py-0.5 rounded-full border transition-colors cursor-pointer ${
                            formName === 'openai'
                              ? 'bg-[#E8F0FE] text-[#1967D2] border-[#1967D2]/40 font-semibold'
                              : 'bg-[#F8F9FA] text-[#3C4043] border-[#DADCE0] hover:bg-[#F1F3F4]'
                          }`}
                        >
                          OpenAI
                        </button>
                        <button
                          type="button"
                          onClick={() => applyPreset('google', 'google', 'https://generativelanguage.googleapis.com/v1beta', 'gemini-2.0-flash')}
                          className={`text-[11px] px-2.5 py-0.5 rounded-full border transition-colors cursor-pointer ${
                            formName === 'google'
                              ? 'bg-[#E8F0FE] text-[#1967D2] border-[#1967D2]/40 font-semibold'
                              : 'bg-[#F8F9FA] text-[#3C4043] border-[#DADCE0] hover:bg-[#F1F3F4]'
                          }`}
                        >
                          Google Gemini
                        </button>
                      </div>
                    )}

                  <div className="provider-form-grid mb-3">
                    <div className="form-group">
                      <label className="form-label">{t('settings_provider_name')} *</label>
                      <input
                        type="text"
                        value={formName}
                        onChange={(e) => setFormName(e.target.value)}
                        placeholder="e.g. tokenharbor, xkiro, openrouter, my-ollama"
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
                        <option value="openai-compatible">{t('settings_kind_openai_compat')}</option>
                        <option value="openai">{t('settings_kind_openai_official')}</option>
                        <option value="google">{t('settings_kind_google_gemini')}</option>
                      </select>
                    </div>
                  </div>

                  <div className="form-group mb-3">
                    <div className="flex items-center justify-between mb-1">
                      <label className="form-label mb-0">{t('settings_model')} *</label>
                      <div className="flex items-center gap-2">
                        {formDiscoveredModels.length > 0 && (
                          <button
                            type="button"
                            onClick={() => setCustomFormModelMode(!customFormModelMode)}
                            className="text-[11px] text-[#1967D2] hover:text-[#174EA6] underline font-medium"
                          >
                            {customFormModelMode ? t('settings_dropdown_model_toggle') : t('settings_custom_model_toggle')}
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={handleScanFormModels}
                          disabled={scanningFormModels || (!formApiKey && !editingName)}
                          className="text-[11px] px-2.5 py-1 rounded-full bg-[#E8F0FE] hover:bg-[#D2E3FC] text-[#1967D2] font-medium border border-[#1967D2]/20 flex items-center gap-1 transition-all disabled:opacity-40"
                          title={t('settings_scan_models')}
                        >
                          <RefreshCw size={11} className={scanningFormModels ? "animate-spin" : ""} />
                          <span>{scanningFormModels ? t('settings_scanning_models') : t('settings_scan_models')}</span>
                        </button>
                      </div>
                    </div>

                    {formDiscoveredModels.length > 0 && !customFormModelMode ? (
                      <select
                        value={formModel}
                        onChange={(e) => setFormModel(e.target.value)}
                        className="form-select"
                        required
                      >
                        <option value="">{t('settings_select_model_placeholder')}</option>
                        {formDiscoveredModels.filter((m) => m.toLowerCase().includes(':free')).length > 0 && (
                          <optgroup label={t('settings_free_models_group')}>
                            {formDiscoveredModels
                              .filter((m) => m.toLowerCase().includes(':free'))
                              .map((m) => (
                                <option key={m} value={m}>
                                  {m}
                                </option>
                              ))}
                          </optgroup>
                        )}
                        <optgroup label={t('settings_all_models_group')}>
                          {formDiscoveredModels
                            .filter((m) => !m.toLowerCase().includes(':free'))
                            .map((m) => (
                              <option key={m} value={m}>
                                {m}
                              </option>
                            ))}
                        </optgroup>
                      </select>
                    ) : (
                      <input
                        type="text"
                        value={formModel}
                        onChange={(e) => setFormModel(e.target.value)}
                        placeholder="e.g. qwen/qwen3.7-flash:free, gpt-4o-mini, gemini-2.0-flash"
                        required
                        className="form-input"
                      />
                    )}
                  </div>

                  <div className="form-group mb-3">
                    <label className="form-label">{t('settings_base_url')}</label>
                    <input
                      type="text"
                      value={formBaseUrl}
                      onChange={(e) => setFormBaseUrl(e.target.value)}
                      placeholder="e.g. https://tokenharbor.ai/v1, https://api.xkiro.com/v1"
                      className="form-input"
                    />
                  </div>

                  <div className="form-group mb-3">
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
                        className="absolute right-2.5 top-2.5 text-[#5F6368] hover:text-[#202124]"
                        tabIndex={-1}
                      >
                        {showApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
                      </button>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 mb-4">
                    <label className="flex items-center gap-2 text-xs text-[#202124] cursor-pointer">
                      <input
                        type="checkbox"
                        checked={formIsActive}
                        onChange={(e) => setFormIsActive(e.target.checked)}
                        className="rounded bg-white border-[#DADCE0] text-[#1967D2] focus:ring-[#1967D2]"
                      />
                      <span>{t('settings_btn_activate')}</span>
                    </label>
                  </div>

                  {testResult && (
                    <div className={testResult.success ? 'test-banner-success mb-3' : 'test-banner-error mb-3'}>
                      {testResult.success ? (
                        <>
                          <CheckCircle size={14} className="flex-shrink-0" />
                          <span>{t('settings_test_success')} ({testResult.latency} ms)</span>
                        </>
                      ) : (
                        <>
                          <AlertTriangle size={14} className="flex-shrink-0" />
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
                      className="btn-secondary btn-sm"
                    >
                      {testingName ? t('settings_btn_testing') : t('settings_btn_test')}
                    </button>
                    <button
                      type="submit"
                      disabled={isLoading}
                      className="btn-primary btn-sm"
                    >
                      {isLoading ? '...' : t('settings_btn_save')}
                    </button>
                  </div>
                </form>
              )}
            </div>
          )}

          {/* TAB: ROLE ASSIGNMENTS */}
          {activeTab === 'roles' && (() => {
            const availableProviders = providers.filter((p) => p.has_api_key || p.is_active);
            const plannerProv = roleMappings.planner?.provider || activeProviderName;
            const synthProv = roleMappings.synthesizer?.provider || activeProviderName;
            const plannerDefaultModel = providers.find((p) => p.name.toLowerCase() === plannerProv.toLowerCase())?.model || '';
            const synthDefaultModel = providers.find((p) => p.name.toLowerCase() === synthProv.toLowerCase())?.model || '';
            const plannerEffectiveModel = roleMappings.planner?.model?.trim() || plannerDefaultModel;
            const synthEffectiveModel = roleMappings.synthesizer?.model?.trim() || synthDefaultModel;

            const isSamePlannerSynthesizer = Boolean(
              plannerProv &&
              synthProv &&
              plannerProv.toLowerCase() === synthProv.toLowerCase() &&
              plannerEffectiveModel &&
              synthEffectiveModel &&
              plannerEffectiveModel.toLowerCase() === synthEffectiveModel.toLowerCase()
            );

            const roleCards = [
              {
                key: 'planner' as const,
                title: t('role_planner_title'),
                desc: t('role_planner_desc'),
                icon: Compass,
                iconColor: 'text-[#1967D2]',
                iconBg: 'bg-[#E8F0FE] border-[#1967D2]/25',
                tagClass: 'text-[#174EA6] bg-[#E8F0FE] border-[#1967D2]/25',
              },
              {
                key: 'reviewer' as const,
                title: t('role_reviewer_title'),
                desc: t('role_reviewer_desc'),
                icon: ShieldAlert,
                iconColor: 'text-[#C5221F]',
                iconBg: 'bg-[#FCE8E6] border-[#C5221F]/25',
                tagClass: 'text-[#A50E0E] bg-[#FCE8E6] border-[#C5221F]/25',
              },
              {
                key: 'synthesizer' as const,
                title: t('role_synthesizer_title'),
                desc: t('role_synthesizer_desc'),
                icon: GitMerge,
                iconColor: 'text-[#F9AB00]',
                iconBg: 'bg-[#FEF7E0] border-[#F9AB00]/30',
                tagClass: 'text-[#7A4F01] bg-[#FEF7E0] border-[#F9AB00]/30',
              },
            ];

            return (
              <div className="space-y-4">
                <div className="settings-section-header mb-1">
                  <span className="text-xs text-[#5F6368]">
                    {t('settings_roles_desc')}
                  </span>
                </div>

                {isSamePlannerSynthesizer && (
                  <div className="p-3 bg-[#FEF7E0] border border-[#F9AB00]/30 rounded-xl text-[#7A4F01] text-xs flex items-center gap-2.5">
                    <AlertTriangle size={16} className="flex-shrink-0 text-[#F9AB00]" />
                    <span>{t('role_same_model_warning')}</span>
                  </div>
                )}

                <div className="space-y-3.5">
                  {roleCards.map((r) => {
                    const RoleIcon = r.icon;
                    const assignment = roleMappings[r.key];
                    const currentProviderName = assignment?.provider || '';
                    const matchedProvider = providers.find(
                      (p) => p.name.toLowerCase() === currentProviderName.toLowerCase()
                    );
                    const defaultModelHint = matchedProvider?.model;
                    const availableModels = currentProviderName ? (providerModelsCache[currentProviderName] || []) : [];
                    const isLoadingModels = currentProviderName ? loadingModels[currentProviderName] : false;
                    const isManual = customModelMode[r.key];

                    return (
                      <div
                        key={r.key}
                        className="role-card-modern"
                      >
                        <div className="grid grid-cols-1 md:grid-cols-12 gap-5 items-center">
                          {/* Role Details */}
                          <div className="md:col-span-5 space-y-2">
                            <div className="flex items-center gap-3">
                              <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 border ${r.iconBg} ${r.iconColor}`}>
                                <RoleIcon size={16} />
                              </div>
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2 flex-wrap">
                                  <span className={`text-[10px] font-mono font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border ${r.tagClass}`}>
                                    {r.key.toUpperCase()}
                                  </span>
                                  <h4 className="text-sm font-semibold text-[#202124] truncate">
                                    {r.title}
                                  </h4>
                                </div>
                                <div className="mt-1 flex items-center gap-1.5">
                                  {currentProviderName ? (
                                    <span className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-full bg-[#E8F0FE] text-[#174EA6] border border-[#1967D2]/25">
                                      <span className="w-1.5 h-1.5 rounded-full bg-[#1967D2]" />
                                      Custom: {currentProviderName}
                                    </span>
                                  ) : (
                                    <span className="inline-flex items-center text-[10px] px-2 py-0.5 rounded-full bg-[#F1F3F4] text-[#3C4043] border border-[#DADCE0]">
                                      Default: {activeProviderName || 'Active'}
                                    </span>
                                  )}
                                </div>
                              </div>
                            </div>

                            <p className="text-xs text-[#5F6368] leading-relaxed pl-0.5">
                              {r.desc}
                            </p>
                          </div>

                          {/* Control Box */}
                          <div className="md:col-span-7">
                            <div className="role-control-box space-y-2.5">
                              <div>
                                <label className="block text-[11px] font-medium uppercase tracking-wider text-[#5F6368] mb-1">
                                  {t('role_provider_label')}
                                </label>
                                <select
                                  value={currentProviderName}
                                  onChange={(e) => handleRoleProviderChange(r.key, e.target.value)}
                                  className="role-control-input form-select py-1.5 px-2.5 text-xs w-full"
                                >
                                  <option value="">
                                    {t('role_provider_default').replace('{provider}', activeProviderName || 'Active')}
                                  </option>
                                  {availableProviders.map((p) => (
                                    <option key={p.name} value={p.name}>
                                      {p.name} ({p.kind})
                                    </option>
                                  ))}
                                </select>
                              </div>

                              <div>
                                <div className="flex items-center justify-between mb-1">
                                  <div className="flex items-center gap-1.5">
                                    <label className="text-[11px] font-medium uppercase tracking-wider text-[#5F6368]">
                                      {t('role_model_label')}
                                    </label>
                                    {availableModels.length > 0 && (
                                      <span className="text-[10px] text-emerald-600 font-mono px-1.5 py-0.2 rounded bg-emerald-50 border border-emerald-200">
                                        ✓ {t('role_models_available_count').replace('{count}', String(availableModels.length))}
                                      </span>
                                    )}
                                    {isLoadingModels && (
                                      <span className="text-[10px] text-[#1967D2] flex items-center gap-1 font-mono">
                                        <RefreshCw size={10} className="animate-spin" />
                                        {t('role_scanning_models_short')}
                                      </span>
                                    )}
                                  </div>

                                  <div className="flex items-center gap-2">
                                    {currentProviderName && availableModels.length > 0 && (
                                      <button
                                        type="button"
                                        onClick={() => setCustomModelMode((prev) => ({ ...prev, [r.key]: !prev[r.key] }))}
                                        className="text-[10px] text-[#1967D2] hover:underline"
                                      >
                                        {isManual ? t('settings_dropdown_model_toggle') : t('settings_custom_model_toggle')}
                                      </button>
                                    )}
                                    {currentProviderName && defaultModelHint && !availableModels.length && (
                                      <span className="text-[10px] text-[#5F6368] font-mono">
                                        {t('role_default_model_prefix').replace('{model}', defaultModelHint)}
                                      </span>
                                    )}
                                  </div>
                                </div>

                                {!currentProviderName ? (
                                  <input
                                    type="text"
                                    disabled
                                    value=""
                                    placeholder={t('role_model_placeholder')}
                                    className="role-control-input form-input py-1.5 px-2.5 text-xs w-full opacity-60 cursor-not-allowed bg-[#F1F3F4]"
                                  />
                                ) : availableModels.length > 0 && !isManual ? (
                                  <select
                                    value={assignment?.model ?? ''}
                                    onChange={(e) => handleRoleModelChange(r.key, e.target.value)}
                                    className="role-control-input form-select py-1.5 px-2.5 text-xs w-full"
                                  >
                                    <option value="">
                                      {defaultModelHint
                                        ? t('role_default_model_prefix').replace('{model}', defaultModelHint)
                                        : t('role_model_placeholder')}
                                    </option>
                                    {availableModels.filter((m) => m.toLowerCase().includes(':free')).length > 0 && (
                                      <optgroup label={t('settings_free_models_group')}>
                                        {availableModels
                                          .filter((m) => m.toLowerCase().includes(':free'))
                                          .map((m) => (
                                            <option key={m} value={m}>
                                              {m}
                                            </option>
                                          ))}
                                      </optgroup>
                                    )}
                                    <optgroup label={t('settings_all_models_group')}>
                                      {availableModels
                                        .filter((m) => !m.toLowerCase().includes(':free'))
                                        .map((m) => (
                                          <option key={m} value={m}>
                                            {m}
                                          </option>
                                        ))}
                                    </optgroup>
                                  </select>
                                ) : (
                                  <div className="relative">
                                    <input
                                      type="text"
                                      list={`model-suggestions-${r.key}`}
                                      value={assignment?.model ?? ''}
                                      onChange={(e) => handleRoleModelChange(r.key, e.target.value)}
                                      placeholder={
                                        defaultModelHint
                                          ? t('role_default_model_prefix').replace('{model}', defaultModelHint)
                                          : t('role_model_placeholder')
                                      }
                                      className="role-control-input form-input py-1.5 px-2.5 text-xs w-full"
                                    />
                                    <datalist id={`model-suggestions-${r.key}`}>
                                      {defaultModelHint && <option value={defaultModelHint} />}
                                      {availableModels.map((m) => (
                                        <option key={m} value={m} />
                                      ))}
                                    </datalist>
                                  </div>
                                )}
                              </div>

                              {/* Custom Role API Key Override */}
                              {currentProviderName && (
                                <div>
                                  <div className="flex items-center justify-between mb-1">
                                    <div className="flex items-center gap-1.5">
                                      <label className="text-[11px] font-medium uppercase tracking-wider text-[#5F6368] flex items-center gap-1">
                                        <Key size={11} className={assignment?.has_custom_key ? 'text-[#1E8E3E]' : 'text-[#9AA0A6]'} />
                                        {t('role_api_key_label')}
                                      </label>
                                      {assignment?.has_custom_key && !roleApiKeyInputs[r.key] && (
                                        <span className="text-[10px] text-emerald-600 font-mono px-1.5 py-0.2 rounded bg-emerald-50 border border-emerald-200">
                                          ✓ {t('role_api_key_saved')}
                                        </span>
                                      )}
                                    </div>

                                    {assignment?.has_custom_key && (
                                      <button
                                        type="button"
                                        onClick={() => {
                                          setRoleApiKeyInputs((prev) => ({ ...prev, [r.key]: '' }));
                                          setRoleMappings((prev) => ({
                                            ...prev,
                                            [r.key]: prev[r.key] ? { ...prev[r.key]!, has_custom_key: false } : null,
                                          }));
                                        }}
                                        className="text-[10px] text-red-600 hover:text-red-700 underline"
                                      >
                                        {t('role_api_key_reset')}
                                      </button>
                                    )}
                                  </div>

                                  <div className="relative">
                                    <input
                                      type={showRoleApiKey[r.key] ? 'text' : 'password'}
                                      value={roleApiKeyInputs[r.key] ?? ''}
                                      onChange={(e) => setRoleApiKeyInputs((prev) => ({ ...prev, [r.key]: e.target.value }))}
                                      placeholder={
                                        assignment?.has_custom_key
                                          ? `•••••••• (${t('role_api_key_saved')})`
                                          : t('role_api_key_placeholder')
                                      }
                                      className="role-control-input form-input py-1.5 px-2.5 pr-8 text-xs w-full font-mono"
                                    />
                                    <button
                                      type="button"
                                      onClick={() => setShowRoleApiKey((prev) => ({ ...prev, [r.key]: !prev[r.key] }))}
                                      className="absolute right-2 top-1/2 -translate-y-1/2 text-[#5F6368] hover:text-[#202124]"
                                      title={showRoleApiKey[r.key] ? t('settings_hide_api_key') : t('settings_show_api_key')}
                                    >
                                      {showRoleApiKey[r.key] ? <EyeOff size={13} /> : <Eye size={13} />}
                                    </button>
                                  </div>
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div className="role-footer-bar">
                  <div className="flex items-center gap-1.5 text-xs text-[#5F6368]">
                    <Info size={14} className="text-[#1967D2] flex-shrink-0" />
                    <span>{t('role_footer_notice')}</span>
                  </div>

                  <button
                    type="button"
                    onClick={handleSaveRoleMappings}
                    disabled={isSavingRoles}
                    className="btn-primary btn-sm flex items-center gap-2 px-4 py-2 font-medium"
                  >
                    {isSavingRoles ? (
                      <>
                        <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        <span>{t('role_saving')}</span>
                      </>
                    ) : (
                      <>
                        <CheckCircle size={15} />
                        <span>{t('role_btn_save')}</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            );
          })()}

          {/* TAB 2: ADMIN SECURITY */}
          {activeTab === 'security' && (
            <form onSubmit={handleChangePassword} className="space-y-4 max-w-md">
              <p className="text-xs text-[#5F6368] mb-4 leading-relaxed">
                {t('settings_security_desc')}
              </p>

              <div className="form-group mb-3">
                <label className="form-label">{t('settings_current_password')} *</label>
                <div className="relative">
                  <input
                    type={showCurrentPassword ? 'text' : 'password'}
                    value={currentPassword}
                    onChange={(e) => setCurrentPassword(e.target.value)}
                    required
                    className="form-input pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                    className="absolute right-2.5 top-2.5 text-[#5F6368] hover:text-[#202124] focus:outline-none focus:text-[#1967D2] p-1 rounded-full transition-colors"
                    aria-label={showCurrentPassword ? t('auth_hide_password') : t('auth_show_password')}
                  >
                    {showCurrentPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <div className="form-group mb-3">
                <label className="form-label">{t('settings_new_password')} *</label>
                <div className="relative">
                  <input
                    type={showNewPassword ? 'text' : 'password'}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder={t('auth_password_placeholder')}
                    required
                    className="form-input pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowNewPassword(!showNewPassword)}
                    className="absolute right-2.5 top-2.5 text-[#5F6368] hover:text-[#202124] focus:outline-none focus:text-[#1967D2] p-1 rounded-full transition-colors"
                    aria-label={showNewPassword ? t('auth_hide_password') : t('auth_show_password')}
                  >
                    {showNewPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <div className="form-group mb-4">
                <label className="form-label">{t('auth_confirm_password_label')} *</label>
                <div className="relative">
                  <input
                    type={showConfirmNewPassword ? 'text' : 'password'}
                    value={confirmNewPassword}
                    onChange={(e) => setConfirmNewPassword(e.target.value)}
                    required
                    className="form-input pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmNewPassword(!showConfirmNewPassword)}
                    className="absolute right-2.5 top-2.5 text-[#5F6368] hover:text-[#202124] focus:outline-none focus:text-[#1967D2] p-1 rounded-full transition-colors"
                    aria-label={showConfirmNewPassword ? t('auth_hide_password') : t('auth_show_password')}
                  >
                    {showConfirmNewPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <div className="pt-2">
                <button
                  type="submit"
                  disabled={isChangingPass}
                  className="btn-primary"
                >
                  {isChangingPass ? '...' : t('settings_btn_change_password')}
                </button>
              </div>
            </form>
          )}
          </div>
        </div>
      </div>

      <ConfirmModal
        isOpen={Boolean(deletingProviderName)}
        title={t('settings_confirm_delete_title')}
        message={
          <span>
            {t('settings_confirm_delete_desc').replace('{name}', deletingProviderName || '')}
          </span>
        }
        confirmText={t('settings_action_delete')}
        cancelText={t('modal_btn_cancel')}
        variant="danger"
        isLoading={isLoading}
        onClose={() => setDeletingProviderName(null)}
        onConfirm={handleConfirmDelete}
      />
    </div>
  );
});
