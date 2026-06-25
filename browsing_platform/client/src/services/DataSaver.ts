import server, {HTTP_METHODS} from "./server";
import {AnnotatableEntityType, IAnnotatableEntity, IMediaPart} from "../types/entities";

/* Media Part */
export const deleteMediaPart = async (mediaPartId: number): Promise<void> => {
    return await server.post("media_part/" + mediaPartId, {}, HTTP_METHODS.delete);
}

export const saveMediaPart = async (mediaPart: IMediaPart): Promise<IMediaPart> => {
    return await server.post("media_part/", mediaPart);
}

/* Annotations */
export const saveAnnotations = async (entity: IAnnotatableEntity, entityType: AnnotatableEntityType): Promise<void> => {
    return await server.post(`annotate/${entityType}/${entity.id}`, {
        tags: entity.tags?.map(t => ({id: t.id, notes: t.assignment_notes ?? null})),
    });
}
