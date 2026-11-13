import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { optionFeedbackClass } from './gameFeel';

describe('lightweight correct feedback', () => {
  it('marks the correct option for the original success animation', () => {
    const className = optionFeedbackClass(
      'answer-token',
      'answer-token',
      { correct: true, correct_option_tokens: ['answer-token'] },
    );
    expect(className).toContain('correct-option');
    expect(className).toContain('success-pop');
  });

  it('keeps a reduced-motion color and border fallback', () => {
    const css = readFileSync(new URL('./style.css', import.meta.url), 'utf8');
    expect(css).toContain('@media (prefers-reduced-motion: reduce)');
    expect(css).toMatch(/prefers-reduced-motion:[\s\S]*animation:\s*none/);
    expect(css).toMatch(/\.answer-grid button\.correct-option[\s\S]*border-color/);
  });
});
