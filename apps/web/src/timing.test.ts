import { describe, expect, it } from 'vitest';
import { elapsedFromMonotonic, formatDuration, rankedElapsed } from './timing';

describe('millisecond game clock', () => {
  it('formats MM:SS.mmm', () => {
    expect(formatDuration(0)).toBe('00:00.000');
    expect(formatDuration(61_007)).toBe('01:01.007');
    expect(formatDuration(6_000_999)).toBe('100:00.999');
  });

  it('recovers elapsed time from the monotonic clock after an animation pause', () => {
    expect(elapsedFromMonotonic(1_000, 100, 5_100)).toBe(6_000);
    expect(rankedElapsed(6_000, 1.3)).toBe(7_800);
  });
});
