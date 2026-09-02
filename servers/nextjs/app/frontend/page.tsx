// ORPHANED (inherited from upstream presenton.ai, kept for reference only):
// no in-app Link/router.push targets "/frontend" anywhere. Renders the
// upstream onboarding wizard (components/Home.tsx), not the live e& app.
// See CLAUDE.md's "Route reachability map" before trusting this as real UI.
import AuthGate from "@/components/Auth/AuthGate";
import Home from "@/components/Home";
import { ConfigurationInitializer } from "./ConfigurationInitializer";
import { isAuthDisabled } from "@/utils/auth";
import { getServerAuthStatus } from "@/utils/serverAuth";

const page = async () => {
    if (isAuthDisabled()) {
        return (
            <ConfigurationInitializer>
                <Home />
            </ConfigurationInitializer>
        );
    }

    const status = await getServerAuthStatus();
    if (status.configured && status.authenticated) {
        return (
            <ConfigurationInitializer>
                <Home />
            </ConfigurationInitializer>
        );
    }

    return <AuthGate />;
};

export default page;
