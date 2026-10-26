import type { User } from './types';

export type PageAccess = 'authenticated' | 'teacher' | 'admin' | 'staff';

export function hasPermission(user: User | null, permission: string): boolean {
	return !!user && !user.is_bootstrap && user.permissions.includes(permission);
}

/** Page navigation hierarchy; FastAPI retains its explicit business-operation roles. */
export function canAccess(user: User | null, access: PageAccess = 'authenticated'): boolean {
	if (!user) return false;
	if (access === 'authenticated') return true;
	if (access === 'admin') return hasPermission(user, 'users.manage');
	if (access === 'staff')
		return (
			hasPermission(user, 'users.read') ||
			hasPermission(user, 'teaching.read') ||
			hasPermission(user, 'kholleur.access')
		);
	return hasPermission(user, 'teacher.access');
}
