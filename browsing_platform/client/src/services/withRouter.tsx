import {
    Location,
    NavigateFunction,
    Params,
    SetURLSearchParams,
    useLocation,
    useNavigate,
    useParams,
    useSearchParams,
} from "react-router-dom";
import React from "react";

export interface IRouterProps {
    location: Location<any>,
    navigate: NavigateFunction,
    params: Readonly<Params<string>>,
    searchParams: URLSearchParams,
    setSearchParams: SetURLSearchParams,
    pageTitle: string,
    setPageTitle: (newTitle: string) => void,
}

export default function withRouter(Component: any) {
    const setPageTitle = (newTitle: string) => {
            document.title = `${newTitle} | Browsing Platform`;
        }

    function ComponentWithRouterProp(props:any) {
        const location = useLocation();
        const navigate = useNavigate();
        const params = useParams();
        const [searchParams, setSearchParams] = useSearchParams();
        return (
            <Component
                {...props}
                location = {location}
                navigate = {navigate}
                params = {params}
                searchParams = {searchParams}
                setSearchParams = {setSearchParams}
                pageTitle = {document.title}
                setPageTitle = {setPageTitle}
            />
        );
    }

    return ComponentWithRouterProp;
}