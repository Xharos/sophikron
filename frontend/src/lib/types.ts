/** Public profile returned by FastAPI, without session credentials. */
export interface User {
	id: number;
	username: string;
	first_name: string | null;
	last_name: string | null;
	email: string | null;
	status: string;
	roles: string[];
	permissions: string[];
	email_verified: boolean;
	is_bootstrap: boolean;
	created_at: string;
}

export interface Invitation {
	token: string;
	expires_at: string;
}

/** Activity metadata is available only from the authenticated account endpoint. */
export interface Account extends User {
	updated_at: string;
	last_login_at: string | null;
	password_changed_at: string | null;
	email_verified_at: string | null;
	login_count: number;
}

export interface Promotion {
	id: number;
	year: number;
	identifier: string;
	color: string;
	is_active: boolean;
	member_count?: number;
	student_count?: number;
}

export interface Page<T> {
	items: T[];
	total: number;
	offset: number;
	limit: number;
}

export interface DirectoryUser {
	id: number;
	username: string;
	first_name: string;
	last_name: string;
	status: string;
	created_at?: string;
	roles?: string[];
	email?: string | null;
	promotions?: Promotion[];
	group_assignments?: import('./groups').GroupAssignment[];
}

export interface AdminAccount extends Account {
	archived_at: string | null;
	invitation: { status: string; expires_at: string | null; purpose: string | null };
	group_assignments?: import('./groups').GroupAssignment[];
}

export interface AccessInvitation {
	delivery: 'email' | 'manual';
	purpose: 'activation' | 'reset';
	expires_at: string;
	token: string | null;
	link?: string;
}

export interface DashboardSummary {
	active_subjects: number;
	archived_subjects: number;
	subject_teachers: number;
	total_lessons: number;
	kholleurs: number;
	total_accounts: number;
	pending_accounts: number;
	active_accounts: number;
	archived_accounts: number;
	total_promotions: number;
	active_promotions: number;
}

export interface ActivityEvent {
	id: number;
	occurred_at: string;
	event_type: string;
	actor_user_id: number | null;
	subject_user_id: number | null;
	actor_role: string | null;
	subject_role: string | null;
	actor_profile_available: boolean;
	subject_profile_available: boolean;
	resource_type: string | null;
	resource_id: number | null;
	promotion_snapshot: Pick<Promotion, 'identifier' | 'year' | 'color'> | null;
	data: Record<string, unknown>;
	actor_label: string | null;
	subject_label: string | null;
	resource_label: string | null;
}

export interface EventType {
	code: string;
	label: string;
	icon: string;
	message: string;
}

export interface EventPage {
	items: ActivityEvent[];
	next_cursor: string | null;
}

export interface BacSubject {
	name: string;
	grade: number | null;
}
export interface Baccalaureate {
	label: string | null;
	year: number | null;
	overall_grade: number | null;
	subjects: BacSubject[];
}
export interface ReferenceAdult {
	first_name: string;
	last_name: string;
	phone: string;
}
export interface SchoolProfile {
	birth_date: string | null;
	city: string | null;
	postal_code: string | null;
	commune_code: string | null;
	previous_school: string | null;
	baccalaureate: Baccalaureate | null;
	orientation_project: string | null;
	phone: string | null;
	reference_adult: ReferenceAdult | null;
}
export interface FullProfile {
	subject_ids: number[];
	id: number;
	username: string;
	first_name: string;
	last_name: string;
	email: string;
	roles: string[];
	status: string;
	profile_version: number;
	profile: SchoolProfile;
	age: number | null;
	promotions: Promotion[];
	group_assignments?: import('./groups').GroupAssignment[];
	can_edit_all: boolean;
	can_edit_orientation: boolean;
}
export interface Commune {
	code: string;
	nom: string;
	codesPostaux: string[];
}

export interface PromotionArchiveImpact {
	student_count: number;
	accounts_to_disable: number;
	blocked_count: number;
	accounts_to_restore: number;
	accounts_remaining_disabled: number;
}
export interface TeachingTeam {
	subjects: {
		id: number;
		name: string;
		icon: import('./lessons').LessonIcon;
		color: string;
		members: { id: number; first_name: string; last_name: string; roles: string[] }[];
	}[];
	member_count: number;
	teacher_count: number;
	kholleur_count: number;
}
