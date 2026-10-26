<script lang="ts">
	import AccountsPanel from '../../src/lib/components/dashboard/AccountsPanel.svelte';
	import ProfileEditor from '../../src/lib/components/dashboard/ProfileEditor.svelte';
	import type { FullProfile } from '../../src/lib/types';
	import 'bulma/css/bulma.min.css';
	import '../../src/app.css';
	const administrator = !new URL(window.location.href).searchParams.has('teacher');
	const archived = new URL(window.location.href).searchParams.has('archived');
	const promotions = [
		{ id: 1, identifier: 'PT', year: 2026, color: '#244BC1', is_active: true },
		{ id: 2, identifier: 'PTSI', year: 2026, color: '#67449A', is_active: true }
	].filter((promotion) => administrator || promotion.id === 1);
	const profile: FullProfile = {
		id: 3,
		username: 'alice123',
		first_name: 'Alice',
		last_name: 'Martin',
		email: 'martin.alice@test.fr',
		roles: ['user'],
		status: archived ? 'disabled' : 'active',
		profile_version: 0,
		subject_ids: [],
		age: null,
		promotions,
		group_assignments: [
			{ promotion_id: 1, kind: 'halves', number: 1 },
			{ promotion_id: 1, kind: 'thirds', number: 3 },
			{ promotion_id: 1, kind: 'kholles', number: 2 },
			...(administrator ? [{ promotion_id: 2, kind: 'kholles' as const, number: 7 }] : [])
		],
		can_edit_all: administrator,
		can_edit_orientation: true,
		profile: {
			birth_date: null,
			city: null,
			postal_code: null,
			commune_code: null,
			previous_school: null,
			baccalaureate: null,
			orientation_project: null,
			phone: null,
			reference_adult: null
		}
	};
</script>

<main style="padding: 1rem; max-width: 1200px; margin: auto; width: 100%;">
	<AccountsPanel {administrator} currentUserId={99} promotionId={1} />
	<ProfileEditor {profile} currentUserId={99} />
</main>
