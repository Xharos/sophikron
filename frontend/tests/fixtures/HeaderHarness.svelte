<script lang="ts">
	import 'bulma/css/bulma.min.css';
	import '../../src/app.css';
	import Header from '../../src/lib/components/Header.svelte';
	import type { User } from '../../src/lib/types';
	const params = new URL(window.location.href).searchParams;
	const role = params.get('role') ?? 'admin';
	const user: User | null = params.has('anonymous')
		? null
		: {
				id: 1,
				username: 'valentin123',
				first_name: 'Valentin',
				last_name: 'Burgaud',
				email: null,
				status: 'active',
				roles: role === 'admin' ? ['admin', 'teacher'] : [role],
				permissions:
					role === 'user'
						? []
						: role === 'admin'
							? ['users.manage', 'users.read', 'teaching.read']
							: ['teaching.read'],
				email_verified: true,
				is_bootstrap: false,
				created_at: '2026-01-01T00:00:00Z'
			};
</script>

<Header
	{user}
	establishmentName={params.has('long')
		? 'Établissement pédagogique avec un nom particulièrement long'
		: 'Sophikron'}
/>
<main class="p-4" style="margin-top: 20rem;">
	<button type="button" class="button">Action hors du header</button>
</main>
