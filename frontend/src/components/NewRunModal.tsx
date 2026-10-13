import React, { useState, useRef, useEffect, useCallback } from 'react';
import type { CreateRunPayload } from '../types';
import { X, Plus, Trash2, Sparkles, AlertCircle, Info } from 'lucide-react';
import { useI18n } from '../i18nContext';

interface NewRunModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (payload: CreateRunPayload, idempotencyKey: string) => Promise<void>;
  isSubmitting: boolean;
  error?: string | null;
}

interface FormErrors {
  goal?: string;
  requirements?: Record<number, string>;
  generalRequirements?: string;
  maxRounds?: string;
  tokenLimit?: string;
  costLimit?: string;
}

const FieldTooltip: React.FC<{ id: string; content: string }> = ({ id, content }) => (
  <span className="tooltip-wrapper">
    <button
      type="button"
      className="tooltip-trigger-btn"
      aria-describedby={id}
      aria-label={content}
      tabIndex={0}
    >
      <Info size={14} />
    </button>
    <span id={id} role="tooltip" className="tooltip-popover">
      {content}
    </span>
  </span>
);

export const NewRunModal: React.FC<NewRunModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
  isSubmitting,
  error,
}) => {
  const { t } = useI18n();

  // Preserved exact default values
  const [goal, setGoal] = useState('Design high-throughput distributed event broker');
  const [requirements, setRequirements] = useState<string[]>([
    'Support at least 50k messages per second with sub-5ms p99 latency',
    'Provide at-least-once message delivery guarantee with idempotent deduplication',
    'Persist state to disk with append-only write-ahead log',
  ]);
  const [mode, setMode] = useState<'greenfield' | 'repo'>('greenfield');
  const [tokenLimit, setTokenLimit] = useState(250000);
  const [costLimit, setCostLimit] = useState(5.0);
  const [maxRounds, setMaxRounds] = useState(2);

  // Validation state
  const [errors, setErrors] = useState<FormErrors>({});

  // Element refs for focus and scrolling
  const goalRef = useRef<HTMLTextAreaElement>(null);
  const reqRefs = useRef<(HTMLInputElement | null)[]>([]);
  const maxRoundsRef = useRef<HTMLInputElement>(null);
  const tokenLimitRef = useRef<HTMLInputElement>(null);
  const costLimitRef = useRef<HTMLInputElement>(null);
  const previousActiveElementRef = useRef<HTMLElement | null>(null);

  // Modal accessibility: body scroll lock, Escape key, backdrop click, focus restore
  useEffect(() => {
    if (isOpen) {
      previousActiveElementRef.current = document.activeElement as HTMLElement | null;
      const originalOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';

      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === 'Escape' && !isSubmitting) {
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
  }, [isOpen, isSubmitting, onClose]);

  const validateGoal = useCallback((val: string): string | null => {
    if (!val.trim()) return t('val_goal_required');
    return null;
  }, [t]);

  const validateRequirement = useCallback((val: string): string | null => {
    if (!val.trim()) return t('val_req_item_empty');
    return null;
  }, [t]);

  const validateMaxRounds = useCallback((val: number): string | null => {
    if (isNaN(val) || val < 1 || val > 10) return t('val_max_rounds_invalid');
    return null;
  }, [t]);

  const validateTokenLimit = useCallback((val: number): string | null => {
    if (isNaN(val) || val < 0) return t('val_token_limit_invalid');
    return null;
  }, [t]);

  const validateCostLimit = useCallback((val: number): string | null => {
    if (isNaN(val) || val < 0) return t('val_cost_limit_invalid');
    return null;
  }, [t]);

  const handleAddRequirement = () => {
    setRequirements((prev) => [...prev, '']);
  };

  const handleUpdateRequirement = (index: number, value: string) => {
    const updated = [...requirements];
    updated[index] = value;
    setRequirements(updated);

    if (errors.requirements?.[index]) {
      const err = validateRequirement(value);
      setErrors((prev) => {
        const nextReqErrors = { ...prev.requirements };
        if (!err) {
          delete nextReqErrors[index];
        } else {
          nextReqErrors[index] = err;
        }
        return {
          ...prev,
          requirements: Object.keys(nextReqErrors).length > 0 ? nextReqErrors : undefined,
          generalRequirements: undefined,
        };
      });
    }
  };

  const handleRemoveRequirement = (index: number) => {
    if (requirements.length <= 1) return;
    setRequirements((prev) => prev.filter((_, i) => i !== index));
    setErrors((prev) => {
      const nextReqErrors: Record<number, string> = {};
      Object.entries(prev.requirements || {}).forEach(([k, v]) => {
        const num = Number(k);
        if (num < index) nextReqErrors[num] = v;
        else if (num > index) nextReqErrors[num - 1] = v;
      });
      return {
        ...prev,
        requirements: Object.keys(nextReqErrors).length > 0 ? nextReqErrors : undefined,
      };
    });
  };

  const handleGoalBlur = () => {
    const err = validateGoal(goal);
    setErrors((prev) => ({ ...prev, goal: err || undefined }));
  };

  const handleRequirementBlur = (index: number) => {
    const val = requirements[index] || '';
    const err = validateRequirement(val);
    setErrors((prev) => {
      const nextReqErrors = { ...prev.requirements };
      if (err) nextReqErrors[index] = err;
      else delete nextReqErrors[index];
      return {
        ...prev,
        requirements: Object.keys(nextReqErrors).length > 0 ? nextReqErrors : undefined,
      };
    });
  };

  const handleMaxRoundsBlur = () => {
    const err = validateMaxRounds(Number(maxRounds));
    setErrors((prev) => ({ ...prev, maxRounds: err || undefined }));
  };

  const handleTokenLimitBlur = () => {
    const err = validateTokenLimit(Number(tokenLimit));
    setErrors((prev) => ({ ...prev, tokenLimit: err || undefined }));
  };

  const handleCostLimitBlur = () => {
    const err = validateCostLimit(Number(costLimit));
    setErrors((prev) => ({ ...prev, costLimit: err || undefined }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const newErrors: FormErrors = {};
    let firstErrorTarget: HTMLElement | null = null;

    // Validate goal
    const goalErr = validateGoal(goal);
    if (goalErr) {
      newErrors.goal = goalErr;
      if (!firstErrorTarget) firstErrorTarget = goalRef.current;
    }

    // Validate requirements
    const reqErrors: Record<number, string> = {};
    let validCount = 0;
    requirements.forEach((req, idx) => {
      const err = validateRequirement(req);
      if (err) {
        reqErrors[idx] = err;
        if (!firstErrorTarget && reqRefs.current[idx]) {
          firstErrorTarget = reqRefs.current[idx];
        }
      } else {
        validCount += 1;
      }
    });

    if (requirements.length === 0 || validCount === 0) {
      newErrors.generalRequirements = t('val_requirements_required');
      if (!firstErrorTarget && reqRefs.current[0]) {
        firstErrorTarget = reqRefs.current[0];
      }
    }
    if (Object.keys(reqErrors).length > 0) {
      newErrors.requirements = reqErrors;
    }

    // Validate max rounds
    const roundsErr = validateMaxRounds(Number(maxRounds));
    if (roundsErr) {
      newErrors.maxRounds = roundsErr;
      if (!firstErrorTarget) firstErrorTarget = maxRoundsRef.current;
    }

    // Validate token limit
    const tokenErr = validateTokenLimit(Number(tokenLimit));
    if (tokenErr) {
      newErrors.tokenLimit = tokenErr;
      if (!firstErrorTarget) firstErrorTarget = tokenLimitRef.current;
    }

    // Validate cost limit
    const costErr = validateCostLimit(Number(costLimit));
    if (costErr) {
      newErrors.costLimit = costErr;
      if (!firstErrorTarget) firstErrorTarget = costLimitRef.current;
    }

    setErrors(newErrors);

    const hasAnyError = Boolean(
      newErrors.goal ||
      newErrors.generalRequirements ||
      newErrors.requirements ||
      newErrors.maxRounds ||
      newErrors.tokenLimit ||
      newErrors.costLimit
    );

    if (hasAnyError) {
      if (firstErrorTarget) {
        firstErrorTarget.scrollIntoView({ behavior: 'smooth', block: 'center' });
        firstErrorTarget.focus();
      }
      return;
    }

    const filteredReqs = requirements.map((r) => r.trim()).filter(Boolean);
    const idemKey = `UI-IDEM-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;
    const payload: CreateRunPayload = {
      goal: goal.trim(),
      requirements: filteredReqs,
      mode,
      token_limit: Number(tokenLimit),
      cost_limit: Number(costLimit),
      max_rounds: Number(maxRounds),
    };

    await onSubmit(payload, idemKey);
  };

  if (!isOpen) return null;

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isSubmitting) {
          onClose();
        }
      }}
    >
      <div className="modal-container" role="dialog" aria-modal="true" aria-labelledby="new-run-title">
        <div className="modal-header">
          <div className="modal-title-group">
            <Sparkles className="text-sky-400" size={20} />
            <h2 id="new-run-title" className="modal-title">{t('modal_new_run_title')}</h2>
          </div>
          <button
            onClick={onClose}
            className="btn-icon"
            aria-label={t('btn_close_modal')}
            disabled={isSubmitting}
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-form" noValidate>
          {error && (
            <div className="error-alert">
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}

          <div className="form-required-legend">
            <span className="form-required-asterisk">*</span>
            <span>{t('modal_required_note')}</span>
          </div>

          <div className="form-group">
            <label htmlFor="run-goal" className="form-label">
              {t('modal_goal_label')}
              <span className="form-required-asterisk" aria-hidden="true">*</span>
            </label>
            <textarea
              id="run-goal"
              ref={goalRef}
              value={goal}
              onChange={(e) => {
                setGoal(e.target.value);
                if (errors.goal && e.target.value.trim()) {
                  setErrors((prev) => ({ ...prev, goal: undefined }));
                }
              }}
              onBlur={handleGoalBlur}
              rows={3}
              placeholder={t('modal_goal_placeholder')}
              className={`form-textarea ${errors.goal ? 'form-textarea-error' : ''}`}
              aria-invalid={Boolean(errors.goal)}
              aria-describedby={errors.goal ? 'goal-error' : undefined}
            />
            {errors.goal && (
              <div id="goal-error" className="form-field-error" role="alert">
                <AlertCircle size={13} className="flex-shrink-0" />
                <span>{errors.goal}</span>
              </div>
            )}
          </div>

          <div className="form-group">
            <div className="flex-between">
              <label className="form-label">
                {t('modal_requirements_label')}
                <span className="form-required-asterisk" aria-hidden="true">*</span>
              </label>
              <button
                type="button"
                onClick={handleAddRequirement}
                className="btn-text"
              >
                <Plus size={14} />
                <span>{t('modal_add_requirement')}</span>
              </button>
            </div>

            <div className="requirements-list">
              {requirements.map((req, idx) => {
                const hasItemError = Boolean(errors.requirements?.[idx]);
                return (
                  <div key={idx} className="mb-2">
                    <div className="requirement-input-row mb-0">
                      <span className="req-idx">REQ-{String(idx + 1).padStart(3, '0')}</span>
                      <input
                        ref={(el) => {
                          reqRefs.current[idx] = el;
                        }}
                        type="text"
                        value={req}
                        onChange={(e) => handleUpdateRequirement(idx, e.target.value)}
                        onBlur={() => handleRequirementBlur(idx)}
                        placeholder={t('modal_requirement_placeholder').replace('{index}', String(idx + 1))}
                        className={`form-input flex-1 ${hasItemError ? 'form-input-error' : ''}`}
                        aria-invalid={hasItemError}
                        aria-describedby={hasItemError ? `req-error-${idx}` : undefined}
                      />
                      {requirements.length > 1 && (
                        <button
                          type="button"
                          onClick={() => handleRemoveRequirement(idx)}
                          className="btn-icon-danger"
                          aria-label={t('modal_remove_requirement')}
                        >
                          <Trash2 size={16} />
                        </button>
                      )}
                    </div>
                    {hasItemError && (
                      <div id={`req-error-${idx}`} className="form-field-error text-xs ml-16" role="alert">
                        <AlertCircle size={12} className="flex-shrink-0" />
                        <span>{errors.requirements?.[idx]}</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            {errors.generalRequirements && (
              <div className="form-field-error" role="alert">
                <AlertCircle size={13} className="flex-shrink-0" />
                <span>{errors.generalRequirements}</span>
              </div>
            )}
          </div>

          <div className="form-grid-2">
            <div className="form-group">
              <div className="flex items-center">
                <label htmlFor="run-mode" className="form-label mb-0">
                  {t('modal_mode_label')}
                </label>
                <FieldTooltip id="tt-run-mode" content={t('tooltip_mode')} />
              </div>
              <select
                id="run-mode"
                value={mode}
                onChange={(e) => setMode(e.target.value as 'greenfield' | 'repo')}
                className="form-select mt-1"
              >
                <option value="greenfield">{t('modal_mode_greenfield')}</option>
                <option value="repo">{t('modal_mode_repo')}</option>
              </select>
            </div>

            <div className="form-group">
              <div className="flex items-center">
                <label htmlFor="max-rounds" className="form-label mb-0">
                  {t('modal_max_rounds')}
                  <span className="form-required-asterisk" aria-hidden="true">*</span>
                </label>
                <FieldTooltip id="tt-max-rounds" content={t('tooltip_max_rounds')} />
              </div>
              <input
                id="max-rounds"
                ref={maxRoundsRef}
                type="number"
                min="1"
                max="10"
                value={maxRounds}
                onChange={(e) => {
                  setMaxRounds(Number(e.target.value));
                  if (errors.maxRounds) {
                    const err = validateMaxRounds(Number(e.target.value));
                    if (!err) setErrors((prev) => ({ ...prev, maxRounds: undefined }));
                  }
                }}
                onBlur={handleMaxRoundsBlur}
                className={`form-input mt-1 ${errors.maxRounds ? 'form-input-error' : ''}`}
                aria-invalid={Boolean(errors.maxRounds)}
                aria-describedby={errors.maxRounds ? 'rounds-error' : undefined}
              />
              {errors.maxRounds && (
                <div id="rounds-error" className="form-field-error" role="alert">
                  <AlertCircle size={13} className="flex-shrink-0" />
                  <span>{errors.maxRounds}</span>
                </div>
              )}
            </div>

            <div className="form-group">
              <div className="flex items-center">
                <label htmlFor="token-limit" className="form-label mb-0">
                  {t('modal_token_limit')}
                </label>
                <FieldTooltip id="tt-token-limit" content={t('tooltip_token_limit')} />
              </div>
              <input
                id="token-limit"
                ref={tokenLimitRef}
                type="number"
                min="0"
                step="10000"
                value={tokenLimit}
                onChange={(e) => {
                  setTokenLimit(Number(e.target.value));
                  if (errors.tokenLimit) {
                    const err = validateTokenLimit(Number(e.target.value));
                    if (!err) setErrors((prev) => ({ ...prev, tokenLimit: undefined }));
                  }
                }}
                onBlur={handleTokenLimitBlur}
                className={`form-input mt-1 ${errors.tokenLimit ? 'form-input-error' : ''}`}
                aria-invalid={Boolean(errors.tokenLimit)}
                aria-describedby={errors.tokenLimit ? 'token-error' : undefined}
              />
              {errors.tokenLimit && (
                <div id="token-error" className="form-field-error" role="alert">
                  <AlertCircle size={13} className="flex-shrink-0" />
                  <span>{errors.tokenLimit}</span>
                </div>
              )}
            </div>

            <div className="form-group">
              <div className="flex items-center">
                <label htmlFor="cost-limit" className="form-label mb-0">
                  {t('modal_cost_limit')}
                </label>
                <FieldTooltip id="tt-cost-limit" content={t('tooltip_cost_limit')} />
              </div>
              <input
                id="cost-limit"
                ref={costLimitRef}
                type="number"
                min="0"
                step="0.5"
                value={costLimit}
                onChange={(e) => {
                  setCostLimit(Number(e.target.value));
                  if (errors.costLimit) {
                    const err = validateCostLimit(Number(e.target.value));
                    if (!err) setErrors((prev) => ({ ...prev, costLimit: undefined }));
                  }
                }}
                onBlur={handleCostLimitBlur}
                className={`form-input mt-1 ${errors.costLimit ? 'form-input-error' : ''}`}
                aria-invalid={Boolean(errors.costLimit)}
                aria-describedby={errors.costLimit ? 'cost-error' : undefined}
              />
              {errors.costLimit && (
                <div id="cost-error" className="form-field-error" role="alert">
                  <AlertCircle size={13} className="flex-shrink-0" />
                  <span>{errors.costLimit}</span>
                </div>
              )}
            </div>
          </div>

          <div className="modal-actions">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary"
              disabled={isSubmitting}
            >
              {t('modal_btn_cancel')}
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={isSubmitting}
            >
              {isSubmitting ? t('modal_btn_creating') : t('modal_btn_create')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
