$ErrorActionPreference = "Continue"

function Invoke-Login {
    param([string]$Email, [string]$Password)
    $body = "{`"email`":`"$Email`",`"password`":`"$Password`"}"
    $tempFile = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($tempFile, $body)
    $resp = curl.exe -s -X POST http://localhost:8001/auth/login -H "Content-Type: application/json" -d "@$tempFile"
    Remove-Item $tempFile
    return ($resp | ConvertFrom-Json).access_token
}

function Invoke-Get {
    param([string]$Path, [string]$Token)
    if ($Token) {
        return curl.exe -s -H "Authorization: Bearer $Token" "http://localhost:8001$Path"
    } else {
        return curl.exe -s "http://localhost:8001$Path"
    }
}

function Invoke-Post {
    param([string]$Path, [string]$Token, [string]$Body)
    $tempFile = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($tempFile, $Body)
    $resp = curl.exe -s -X POST -H "Authorization: Bearer $Token" -H "Content-Type: application/json" -d "@$tempFile" "http://localhost:8001$Path"
    Remove-Item $tempFile
    return $resp
}

function Invoke-Put {
    param([string]$Path, [string]$Token, [string]$Body)
    $tempFile = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($tempFile, $Body)
    $resp = curl.exe -s -X PUT -H "Authorization: Bearer $Token" -H "Content-Type: application/json" -d "@$tempFile" "http://localhost:8001$Path"
    Remove-Item $tempFile
    return $resp
}

function Invoke-Delete {
    param([string]$Path, [string]$Token)
    return curl.exe -s -X DELETE -H "Authorization: Bearer $Token" "http://localhost:8001$Path"
}

function Test-Endpoint {
    param([string]$Method, [string]$Path, [string]$Token, [string]$Body, [int]$ExpectedCode, [string]$Label)
    
    $result = ""
    $statusCode = 0
    
    try {
        switch ($Method) {
            "GET" {
                if ($Token) {
                    $resp = curl.exe -s -w "%{http_code}" -H "Authorization: Bearer $Token" "http://localhost:8001$Path" 2>&1
                } else {
                    $resp = curl.exe -s -w "%{http_code}" "http://localhost:8001$Path" 2>&1
                }
                $respStr = $resp -join ""
                $statusCode = [int]($respStr.Substring($respStr.Length - 3))
            }
            "POST" {
                $tempFile = [System.IO.Path]::GetTempFileName()
                [System.IO.File]::WriteAllText($tempFile, $Body)
                $resp = curl.exe -s -w "%{http_code}" -X POST -H "Authorization: Bearer $Token" -H "Content-Type: application/json" -d "@$tempFile" "http://localhost:8001$Path" 2>&1
                Remove-Item $tempFile
                $respStr = $resp -join ""
                $statusCode = [int]($respStr.Substring($respStr.Length - 3))
            }
            "PUT" {
                $tempFile = [System.IO.Path]::GetTempFileName()
                [System.IO.File]::WriteAllText($tempFile, $Body)
                $resp = curl.exe -s -w "%{http_code}" -X PUT -H "Authorization: Bearer $Token" -H "Content-Type: application/json" -d "@$tempFile" "http://localhost:8001$Path" 2>&1
                Remove-Item $tempFile
                $respStr = $resp -join ""
                $statusCode = [int]($respStr.Substring($respStr.Length - 3))
            }
            "DELETE" {
                $resp = curl.exe -s -w "%{http_code}" -X DELETE -H "Authorization: Bearer $Token" "http://localhost:8001$Path" 2>&1
                $respStr = $resp -join ""
                $statusCode = [int]($respStr.Substring($respStr.Length - 3))
            }
        }
    } catch {
        $statusCode = 0
    }
    
    $pass = $statusCode -eq $ExpectedCode
    $icon = if ($pass) { "PASS" } else { "FAIL" }
    Write-Host "[$icon] $Method $Path | Role=$Label | Expected=$ExpectedCode Got=$statusCode"
    return $pass
}

# ==========================================
# LOGIN ALL USERS
# ==========================================
Write-Host "`n========== LOGIN =========="
$adminToken = Invoke-Login "admin@stratroom.com" "Admin@123"
$adminMemberToken = Invoke-Login "admin@test.com" "Admin@123"
$managerToken = Invoke-Login "manager@stratroom.com" "Admin@123"
$memberToken = Invoke-Login "member@stratroom.com" "Admin@123"

Write-Host "Admin:       $($adminToken.Substring(0,30))..."
Write-Host "AdminMember: $($adminMemberToken.Substring(0,30))..."
Write-Host "Manager:     $($managerToken.Substring(0,30))..."
Write-Host "Member:      $($memberToken.Substring(0,30))..."

$passCount = 0
$failCount = 0

function Count-Result {
    param([bool]$Pass)
    if ($Pass) { $script:passCount++ } else { $script:failCount++ }
}

# ==========================================
# TEST 1: Auth endpoints
# ==========================================
Write-Host "`n========== 1. AUTH =========="
Count-Result (Test-Endpoint "GET" "/auth/me" $adminToken "" 200 "admin")
Count-Result (Test-Endpoint "GET" "/auth/me" $memberToken "" 200 "member")
Count-Result (Test-Endpoint "GET" "/auth/me" "" "" 403 "no-token")

# Bad password
$tempFile = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($tempFile, '{"email":"admin@stratroom.com","password":"wrong"}')
$badLogin = curl.exe -s -w "%{http_code}" -X POST http://localhost:8001/auth/login -H "Content-Type: application/json" -d "@$tempFile" 2>&1
Remove-Item $tempFile
$badLoginStr = $badLogin -join ""
$badCode = [int]($badLoginStr.Substring($badLoginStr.Length - 3))
$pass = $badCode -eq 401
$icon = if ($pass) { "PASS" } else { "FAIL" }
Write-Host "[$icon] POST /auth/login wrong-password | Expected=401 Got=$badCode"
Count-Result $pass

# ==========================================
# TEST 2: Dashboard (all roles should get 200)
# ==========================================
Write-Host "`n========== 2. DASHBOARD =========="
Count-Result (Test-Endpoint "GET" "/dashboard/stats" $adminToken "" 200 "admin")
Count-Result (Test-Endpoint "GET" "/dashboard/stats" $managerToken "" 200 "manager")
Count-Result (Test-Endpoint "GET" "/dashboard/stats" $memberToken "" 200 "member")

# Verify org scoping - check admin@test.com sees different data
$adminDash = (Invoke-Get "/dashboard/stats" $adminToken) | ConvertFrom-Json
$memberDash = (Invoke-Get "/dashboard/stats" $memberToken) | ConvertFrom-Json
Write-Host "  Admin dashboard role: $($adminDash.rbac_role)"
Write-Host "  Member dashboard role: $($memberDash.rbac_role)"

# ==========================================
# TEST 3: GET endpoints (all roles = 200)
# ==========================================
Write-Host "`n========== 3. GET ENDPOINTS (all roles) =========="
$endpoints = @("/tasks", "/scorecards", "/risks", "/initiatives", "/audit-findings", "/complaints", "/incidents", "/budget", "/meetings", "/compliance", "/swot", "/pestel", "/bcp", "/documents")
foreach ($ep in $endpoints) {
    Count-Result (Test-Endpoint "GET" $ep $adminToken "" 200 "admin")
    Count-Result (Test-Endpoint "GET" $ep $managerToken "" 200 "manager")
    Count-Result (Test-Endpoint "GET" $ep $memberToken "" 200 "member")
}

# ==========================================
# TEST 4: POST endpoints (member = 403)
# ==========================================
Write-Host "`n========== 4. POST ENDPOINTS (member=403) =========="
$taskBody = '{"title":"Test Task","description":"test","status":"pending","priority":"medium"}'
Count-Result (Test-Endpoint "POST" "/tasks" $memberToken $taskBody 403 "member")
Count-Result (Test-Endpoint "POST" "/tasks" $managerToken $taskBody 201 "manager")
Count-Result (Test-Endpoint "POST" "/tasks" $adminToken $taskBody 201 "admin")

$scorecardBody = '{"perspective":"Financial","objective":"Test","measure":"Test","target":"100","actual":"50","status":"on-track"}'
Count-Result (Test-Endpoint "POST" "/scorecards" $memberToken $scorecardBody 403 "member")
Count-Result (Test-Endpoint "POST" "/scorecards" $managerToken $scorecardBody 201 "manager")

$riskBody = '{"name":"Test Risk","owner":"Test","inherent_likelihood":3,"inherent_impact":3,"residual_likelihood":2,"residual_impact":2,"description":"test"}'
Count-Result (Test-Endpoint "POST" "/risks" $memberToken $riskBody 403 "member")
Count-Result (Test-Endpoint "POST" "/risks" $managerToken $riskBody 201 "manager")

$auditBody = '{"title":"Test Finding","description":"test","severity":"medium","status":"open"}'
Count-Result (Test-Endpoint "POST" "/audit-findings" $memberToken $auditBody 403 "member")
Count-Result (Test-Endpoint "POST" "/audit-findings" $managerToken $auditBody 201 "manager")

$complaintBody = '{"title":"Test Complaint","description":"test","category":"service","status":"open","severity":"medium"}'
Count-Result (Test-Endpoint "POST" "/complaints" $memberToken $complaintBody 403 "member")
Count-Result (Test-Endpoint "POST" "/complaints" $managerToken $complaintBody 201 "manager")

# ==========================================
# TEST 5: DELETE endpoints (manager = 403)
# ==========================================
Write-Host "`n========== 5. DELETE ENDPOINTS (manager=403) =========="
Count-Result (Test-Endpoint "DELETE" "/risks/99999" $managerToken "" 404 "manager")
Count-Result (Test-Endpoint "DELETE" "/risks/99999" $adminToken "" 404 "admin")
Count-Result (Test-Endpoint "DELETE" "/audit-findings/99999" $managerToken "" 404 "manager")
Count-Result (Test-Endpoint "DELETE" "/complaints/99999" $managerToken "" 404 "manager")

# ==========================================
# TEST 6: Dashboard org_id scoping
# ==========================================
Write-Host "`n========== 6. ORG SCOPING =========="
Count-Result (Test-Endpoint "GET" "/dashboard/stats" $adminToken "" 200 "admin-org1")

# ==========================================
# SUMMARY
# ==========================================
Write-Host "`n========== SUMMARY =========="
Write-Host "PASSED: $passCount"
Write-Host "FAILED: $failCount"
Write-Host "TOTAL:  $($passCount + $failCount)"
$passRate = [math]::Round(($passCount / ($passCount + $failCount)) * 100, 1)
Write-Host "RATE:   $passRate%"
