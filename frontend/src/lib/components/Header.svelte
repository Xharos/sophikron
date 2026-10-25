<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { canAccess } from '#lib/access';
	import type { User } from '#lib/types';
	import Icon from './Icon.svelte';

	let { user, establishmentName }: { user: User | null; establishmentName: string } = $props();
	let expanded = $state(false);
</script>

<header class="site-header">
	<nav class="navbar container" class:anonymous-nav={!user} aria-label="Navigation principale">
		<div class="navbar-brand">
			<a
				class="navbar-item brand"
				href={resolve('/')}
				onclick={() => (expanded = false)}
				aria-label={`${establishmentName}, accueil`}
			>
				<span class="brand-mark" aria-hidden="true"><Icon name="student" size={22} /></span>
				<span class="brand-name">{establishmentName}</span>
			</a>
			{#if user}
				<button
					class="navbar-burger"
					class:is-active={expanded}
					type="button"
					aria-label="Afficher le menu"
					aria-expanded={expanded}
					aria-controls="main-menu"
					onclick={() => (expanded = !expanded)}
				>
					<span aria-hidden="true"></span><span aria-hidden="true"></span><span aria-hidden="true"
					></span><span aria-hidden="true"></span>
				</button>
			{:else}
				<a class="button is-primary header-login" href={resolve('/login')}
					>Se connecter <span aria-hidden="true">↗</span></a
				>
			{/if}
		</div>
		{#if user}
			<div id="main-menu" class="navbar-menu" class:is-active={expanded}>
				<div class="navbar-start">
					<a
						class="navbar-item"
						href={resolve('/lessons')}
						aria-current={page.url.pathname === '/lessons' ? 'page' : undefined}
						onclick={() => (expanded = false)}>Cours</a
					>
					{#if canAccess(user, 'staff')}
						<a
							class="navbar-item"
							href={resolve('/dashboard')}
							aria-current={page.url.pathname === '/dashboard' ? 'page' : undefined}
							onclick={() => (expanded = false)}
							>{canAccess(user, 'admin') ? 'Administration' : 'Mes promotions'}</a
						>
					{/if}
				</div>
				<div class="navbar-end">
					<div class="navbar-item">
						<a
							class="button is-light account-name"
							href={resolve('/me')}
							aria-current={page.url.pathname === '/me' ? 'page' : undefined}
							onclick={() => (expanded = false)}>{user.first_name ?? user.username}</a
						>
					</div>
					<div class="navbar-item">
						<form method="POST" action={resolve('/logout')}>
							<button class="button is-light" type="submit">Se déconnecter</button>
						</form>
					</div>
				</div>
			</div>
		{/if}
	</nav>
</header>
