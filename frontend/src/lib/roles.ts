import type { TeachingTeam } from './types';

/** Shared role catalogue; staff permissions combine independently. */
export const roleLabels: Record<string, string> = {
	user: 'Élève',
	kholleur: 'Khôlleur',
	teacher: 'Enseignant',
	admin: 'Administrateur'
};
export const roleOptions = [
	{ value: 'user', label: roleLabels.user, color: '#174EA6', icon: 'student' },
	{ value: 'kholleur', label: roleLabels.kholleur, color: '#67449A', icon: 'profile' },
	{ value: 'teacher', label: roleLabels.teacher, color: '#175C36', icon: 'teacher' },
	{ value: 'admin', label: roleLabels.admin, color: '#A51D2D', icon: 'admin' }
];

/** Membership eligibility depends on explicit pupil or teaching roles, independently of admin. */
export function canJoinPromotion(roles: readonly string[]): boolean {
	return roles.some((role) => ['user', 'teacher', 'kholleur'].includes(role));
}
/** Compare grants independently of catalogue or response ordering. */
export function sameRoles(left: string[], right: string[]): boolean {
	return left.length === right.length && [...left].sort().join(',') === [...right].sort().join(',');
}
/** Validate the final selection, allowing temporary edits before saving. */
export function roleSelectionError(roles: string[]): string {
	if (!roles.length) return 'Sélectionnez au moins un rôle.';
	if (
		new Set(roles).size !== roles.length ||
		roles.some((role) => !Object.hasOwn(roleLabels, role))
	)
		return 'Sélection de rôles invalide.';
	if (roles.includes('user') && roles.length > 1)
		return 'Le rôle Élève est exclusif : retirez les autres rôles ou décochez Élève.';
	return '';
}

/** List each teaching role separately, teachers first and names sorted within each role. */
export function teachingRoleEntries(members: TeachingTeam['subjects'][number]['members']): {
	member: TeachingTeam['subjects'][number]['members'][number];
	role: 'teacher' | 'kholleur';
}[] {
	const sortedMembers = [...members].sort(
		(left, right) =>
			left.last_name.localeCompare(right.last_name, 'fr', { sensitivity: 'base' }) ||
			left.first_name.localeCompare(right.first_name, 'fr', { sensitivity: 'base' }) ||
			left.id - right.id
	);
	return (['teacher', 'kholleur'] as const).flatMap((role) =>
		sortedMembers
			.filter((member) => member.roles.includes(role))
			.map((member) => ({ member, role }))
	);
}
