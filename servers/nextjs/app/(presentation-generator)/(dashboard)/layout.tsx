import React from 'react'
import DashboardSidebar from './Components/DashboardSidebar'

const layout = ({ children }: { children: React.ReactNode }) => {
    return (
        <div className='flex min-h-screen bg-white'>
            <DashboardSidebar />
            <div className='min-w-0 w-full'>

                {children}
            </div>
        </div>
    )
}

export default layout
