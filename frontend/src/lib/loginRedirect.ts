/** Accept only local destinations and prevent authentication redirect loops. */
export function safeReturnTo(value: unknown): string {
	if (typeof value !== 'string' || value.length > 4096 || !value.startsWith('/')) return '/';
	try {
		const decoded = decodeURIComponent(value);
		if (
			[value, decoded].some(
				(part) =>
					part.startsWith('//') ||
					[...part].some(
						(character) =>
							character === '\\' || character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127
					)
			)
		)
			return '/';
		const target = new URL(value, 'https://sophikron.invalid');
		const decodedPath = new URL(decoded, 'https://sophikron.invalid').pathname.replace(/\/$/, '');
		if (
			target.origin !== 'https://sophikron.invalid' ||
			['/login', '/logout'].includes(decodedPath)
		)
			return '/';
		return target.pathname + target.search + target.hash;
	} catch {
		return '/';
	}
}

/** Carry a protected page's destination through authentication and failed login attempts. */
export function loginDestination(value: string): string {
	return `/login?${new URLSearchParams({ next: safeReturnTo(value) })}`;
}
