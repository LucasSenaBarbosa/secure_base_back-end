from modules.repository.supabase_repository import SupabaseRepository


async def dependencies_are_ready(repository: SupabaseRepository) -> bool:
    return await repository.is_ready()
