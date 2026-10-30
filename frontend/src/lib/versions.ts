/** Compare stable numeric release versions; development versions have no stable ordering. */
export function newerVersion(latest: string, installed: string): boolean {
	const pattern = /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
	const next = pattern.exec(latest)?.slice(1).map(BigInt);
	const current = pattern.exec(installed)?.slice(1).map(BigInt);
	if (!next || !current) return false;
	for (let index = 0; index < 3; index++) {
		if (next[index] !== current[index]) return next[index] > current[index];
	}
	return false;
}

export type BuildState = 'current' | 'behind' | 'experimental' | 'unknown';

/** Classify a build against the cached stable release, prioritizing required updates. */
export function buildState(
	installed: string,
	revision: string | null,
	latest: string | null
): BuildState {
	if (latest && newerVersion(latest, installed)) return 'behind';
	if (revision?.endsWith('-dirty')) return 'experimental';
	if (!latest) return 'unknown';
	if (newerVersion(installed, latest)) return 'experimental';
	if (installed.replace(/^v/, '') === latest.replace(/^v/, '')) return 'current';
	return 'experimental';
}

/** Link only builds whose version matches the release confirmed by the server. */
export function buildReleaseUrl(
	installed: string,
	latest: string | null,
	releaseUrl: string | null
): string | null {
	return latest && installed.replace(/^v/, '') === latest.replace(/^v/, '') ? releaseUrl : null;
}
