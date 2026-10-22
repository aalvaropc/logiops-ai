export function recordedNote(requested, approval) {
  const recorded = approval?.approved_by;
  if (!recorded || recorded === requested) return null;
  return `Recorded as “${recorded}”, not “${requested}”: the server names the approver from your sign-in or access token, `
    + "and keeps the first approval of a plan.";
}
