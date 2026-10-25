/** Shared role choices for account creation, profile editing and badges. */
export const roleLabels: Record<string, string> = {
	user: 'Élève',
	teacher: 'Enseignant',
	admin: 'Administrateur'
};

export const roleOptions = [
	{ value: 'user', label: 'Élève', roles: ['user'] },
	{ value: 'teacher', label: 'Enseignant', roles: ['teacher'] },
	{ value: 'admin', label: 'Administrateur', roles: ['admin'] },
	{ value: 'teacher_admin', label: 'Enseignant et administrateur', roles: ['teacher', 'admin'] }
];

/** Compare grants independently of catalogue or response ordering. */
export function sameRoles(left: string[], right: string[]): boolean {
	return left.length === right.length && [...left].sort().join(',') === [...right].sort().join(',');
}

/** Resolve the existing account's combination without changing its grants. */
export function roleChoice(roles: string[]): string {
	return roleOptions.find((option) => sameRoles(option.roles, roles))?.value ?? 'user';
}

/** Convert one of the four UI choices to explicit backend role codes. */
export function rolesForChoice(value: string): string[] {
	const option = roleOptions.find((item) => item.value === value);
	if (!option) throw new Error('Rôle invalide.');
	return [...option.roles];
}
