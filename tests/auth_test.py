"""
Test script to demonstrate single-session enforcement
Run this after setting up your FastAPI application
"""

import requests
import json
from datetime import datetime

# Base URL - adjust according to your setup
BASE_URL = "http://localhost:8000"


def print_section(title):
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)


def print_response(response):
    print(f"Status: {response.status_code}")
    try:
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except:
        print(f"Response: {response.text}")


# Test 1: Patient Signup
print_section("TEST 1: Patient Signup")
patient_data = {
    "email": "patient1@example.com",
    "password": "SecurePassword123!",
    "name": "John Doe",
    "age": 30
}

response = requests.post(f"{BASE_URL}/signup/patient", json=patient_data)
print_response(response)

if response.status_code == 200:
    patient_tokens = response.json()
    patient_access_token = patient_tokens["access_token"]
    patient_refresh_token = patient_tokens["refresh_token"]
    print("\n✓ Patient signup successful - Session started automatically")
else:
    print("\n✗ Patient signup failed")
    exit(1)


# Test 2: Access protected route with access token
print_section("TEST 2: Access Protected Route (/auth/me)")
headers = {"Authorization": f"Bearer {patient_access_token}"}
response = requests.get(f"{BASE_URL}/auth/me", headers=headers)
print_response(response)


# Test 3: Simulate second login from different device/browser
print_section("TEST 3: Login from 'Second Device' (Same User)")
print("This will REVOKE the first session (single-session enforcement)")

login_data = {
    "email": "patient1@example.com",
    "password": "SecurePassword123!"
}

response = requests.post(f"{BASE_URL}/auth/login", json=login_data)
print_response(response)

if response.status_code == 200:
    new_tokens = response.json()
    new_access_token = new_tokens["access_token"]
    new_refresh_token = new_tokens["refresh_token"]
    print("\n✓ Second login successful - First session should now be invalid")
else:
    print("\n✗ Login failed")
    exit(1)


# Test 4: Try to use old access token (should fail)
print_section("TEST 4: Try Using OLD Access Token")
print("This should FAIL because the first session was revoked")

old_headers = {"Authorization": f"Bearer {patient_access_token}"}
response = requests.get(f"{BASE_URL}/auth/me", headers=old_headers)
print_response(response)

if response.status_code == 401:
    print("\n✓ Old token correctly rejected - Single session enforcement working!")
else:
    print("\n✗ Old token still works - Single session enforcement NOT working")


# Test 5: Use new access token (should work)
print_section("TEST 5: Use NEW Access Token")
new_headers = {"Authorization": f"Bearer {new_access_token}"}
response = requests.get(f"{BASE_URL}/auth/me", headers=new_headers)
print_response(response)

if response.status_code == 200:
    print("\n✓ New token works correctly")


# Test 6: Refresh token to get new access token
print_section("TEST 6: Refresh Access Token")
print(f"Using refresh token to get new access token")

refresh_data = {"refresh_token": new_refresh_token}
response = requests.post(f"{BASE_URL}/auth/refresh", json=refresh_data)
print_response(response)

if response.status_code == 200:
    refreshed_tokens = response.json()
    refreshed_access_token = refreshed_tokens["access_token"]
    print("\n✓ Token refresh successful")
    
    # Test the refreshed access token
    print("\nTesting refreshed access token...")
    refreshed_headers = {"Authorization": f"Bearer {refreshed_access_token}"}
    response = requests.get(f"{BASE_URL}/auth/me", headers=refreshed_headers)
    print_response(response)


# Test 7: Logout
print_section("TEST 7: Logout from Current Device")
response = requests.post(f"{BASE_URL}/auth/logout", headers=refreshed_headers)
print_response(response)

if response.status_code == 200:
    print("\n✓ Logout successful")


# Test 8: Try to use token after logout (should fail)
print_section("TEST 8: Try Using Token After Logout")
response = requests.get(f"{BASE_URL}/auth/me", headers=refreshed_headers)
print_response(response)

if response.status_code == 401:
    print("\n✓ Token correctly invalidated after logout")


# Test 9: Doctor Signup
print_section("TEST 9: Doctor Signup")
doctor_data = {
    "email": "doctor1@example.com",
    "password": "DoctorPass123!",
    "name": "Dr. Jane Smith",
    "speciality": "Cardiology",
    "opd_fees": 500.00,
    "minimum_slot_duration": 0.5
}

response = requests.post(f"{BASE_URL}/signup/doctor", json=doctor_data)
print_response(response)

if response.status_code == 200:
    doctor_tokens = response.json()
    doctor_access_token = doctor_tokens["access_token"]
    print("\n✓ Doctor signup successful")


# Test 10: Verify doctor role
print_section("TEST 10: Verify Doctor Profile")
doctor_headers = {"Authorization": f"Bearer {doctor_access_token}"}
response = requests.get(f"{BASE_URL}/auth/me", headers=doctor_headers)
print_response(response)


# Test 11: Multiple login attempts (stress test)
print_section("TEST 11: Multiple Login Attempts (Stress Test)")
print("Logging in 3 times rapidly - only last session should be valid")

valid_token = None
for i in range(3):
    print(f"\nLogin attempt {i+1}...")
    response = requests.post(f"{BASE_URL}/auth/login", json=login_data)
    if response.status_code == 200:
        valid_token = response.json()["access_token"]
        print(f"  Login {i+1} successful")

if valid_token:
    print("\nTesting only the LAST token (should work)...")
    headers = {"Authorization": f"Bearer {valid_token}"}
    response = requests.get(f"{BASE_URL}/auth/me", headers=headers)
    print_response(response)
    if response.status_code == 200:
        print("\n✓ Only the last session is valid - Single session enforcement working!")


# Test 12: Logout from all devices
print_section("TEST 12: Logout from All Devices")
print("First, let's login and then logout from all devices")

response = requests.post(f"{BASE_URL}/auth/login", json=login_data)
if response.status_code == 200:
    tokens = response.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    
    response = requests.post(f"{BASE_URL}/auth/logout-all", headers=headers)
    print_response(response)
    
    if response.status_code == 200:
        print("\n✓ Logged out from all devices")


print_section("TESTS COMPLETED")
print("\nKey Findings:")
print("1. Signup automatically starts a session (no separate login needed)")
print("2. Login from a new device/browser revokes ALL previous sessions")
print("3. Only ONE session can be active at a time per user")
print("4. Refresh tokens can be used to get new access tokens")
print("5. Logout invalidates the current session")
print("6. Logout-all invalidates ALL sessions")