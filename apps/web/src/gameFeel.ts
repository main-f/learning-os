export type FeedbackState = {
  correct: boolean;
  correct_option_tokens: string[];
};

export function optionFeedbackClass(
  token: string,
  selectedToken: string | null,
  feedback: FeedbackState | null,
): string {
  const classes: string[] = [];
  if (selectedToken === token) classes.push('selected');
  if (feedback?.correct_option_tokens.includes(token)) {
    classes.push('correct-option');
    if (feedback.correct) classes.push('success-pop');
  }
  if (feedback && selectedToken === token && !feedback.correct) classes.push('wrong-option');
  return classes.join(' ');
}
