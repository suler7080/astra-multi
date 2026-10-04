import React, { useState } from 'react';
import type { CreateRunPayload } from '../types';
import { X, Plus, Trash2, Sparkles, AlertCircle } from 'lucide-react';

interface NewRunModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (payload: CreateRunPayload, idempotencyKey: string) => Promise<void>;
  isSubmitting: boolean;
  error?: string | null;
}

export const NewRunModal: React.FC<NewRunModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
  isSubmitting,
  error,
}) => {
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

  if (!isOpen) return null;

  const handleAddRequirement = () => {
    setRequirements([...requirements, '']);
  };

  const handleUpdateRequirement = (index: number, value: string) => {
    const updated = [...requirements];
    updated[index] = value;
    setRequirements(updated);
  };

  const handleRemoveRequirement = (index: number) => {
    if (requirements.length <= 1) return;
    setRequirements(requirements.filter((_, i) => i !== index));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const filteredReqs = requirements.map((r) => r.trim()).filter(Boolean);
    if (!goal.trim() || filteredReqs.length === 0) return;

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

  return (
    <div className="modal-backdrop">
      <div className="modal-container" role="dialog" aria-modal="true" aria-labelledby="new-run-title">
        <div className="modal-header">
          <div className="modal-title-group">
            <Sparkles className="text-sky-400" size={20} />
            <h2 id="new-run-title" className="modal-title">New Architecture Run</h2>
          </div>
          <button
            onClick={onClose}
            className="btn-icon"
            aria-label="Close modal"
            disabled={isSubmitting}
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-form">
          {error && (
            <div className="error-alert">
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}

          <div className="form-group">
            <label htmlFor="run-goal" className="form-label">
              Goal / Architecture Objective <span className="text-rose-400">*</span>
            </label>
            <textarea
              id="run-goal"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              required
              rows={3}
              placeholder="e.g. Design a fault-tolerant payment gateway service with distributed transactions"
              className="form-textarea"
            />
          </div>

          <div className="form-group">
            <div className="flex-between">
              <label className="form-label">
                Architecture Requirements <span className="text-rose-400">*</span>
              </label>
              <button
                type="button"
                onClick={handleAddRequirement}
                className="btn-text"
              >
                <Plus size={14} />
                <span>Add Requirement</span>
              </button>
            </div>

            <div className="requirements-list">
              {requirements.map((req, idx) => (
                <div key={idx} className="requirement-input-row">
                  <span className="req-idx">REQ-{String(idx + 1).padStart(3, '0')}</span>
                  <input
                    type="text"
                    value={req}
                    onChange={(e) => handleUpdateRequirement(idx, e.target.value)}
                    placeholder={`Requirement #${idx + 1}`}
                    required
                    className="form-input flex-1"
                  />
                  {requirements.length > 1 && (
                    <button
                      type="button"
                      onClick={() => handleRemoveRequirement(idx)}
                      className="btn-icon-danger"
                      aria-label="Remove requirement"
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="form-grid-3">
            <div className="form-group">
              <label htmlFor="run-mode" className="form-label">Mode</label>
              <select
                id="run-mode"
                value={mode}
                onChange={(e) => setMode(e.target.value as 'greenfield' | 'repo')}
                className="form-select"
              >
                <option value="greenfield">Greenfield</option>
                <option value="repo">Existing Repo</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="token-limit" className="form-label">Token Budget</label>
              <input
                id="token-limit"
                type="number"
                min="0"
                step="10000"
                value={tokenLimit}
                onChange={(e) => setTokenLimit(Number(e.target.value))}
                className="form-input"
              />
            </div>

            <div className="form-group">
              <label htmlFor="cost-limit" className="form-label">Cost Limit (USD)</label>
              <input
                id="cost-limit"
                type="number"
                min="0"
                step="0.5"
                value={costLimit}
                onChange={(e) => setCostLimit(Number(e.target.value))}
                className="form-input"
              />
            </div>

            <div className="form-group">
              <label htmlFor="max-rounds" className="form-label">Max Rounds</label>
              <input
                id="max-rounds"
                type="number"
                min="1"
                max="10"
                value={maxRounds}
                onChange={(e) => setMaxRounds(Number(e.target.value))}
                className="form-input"
              />
            </div>
          </div>

          <div className="modal-actions">
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary"
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Starting Run...' : 'Launch Architecture Run'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
